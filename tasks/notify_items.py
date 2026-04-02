import asyncio
from datetime import datetime, timedelta, timezone
import traceback  # traceback 모듈 추가


import discord

from core import dnf_api
from core.db import (
    get_all_characters_grouped_by_adventure,
    get_last_checked, update_last_checked,
    get_output_channel,
    update_character_name,
)

from core.logger import logger
from core.models import ALLOWED_RARITIES, COVENANT_CODES, ENHANCE_CODES, SEALED_LOCK_CODES

DEFAULT_PERIOD_SEC = 20  # 타임라인 주기적 체크 주기 (초 단위)
DEFAULT_LOOKBACK_MINUTES = 30  # 기록 없으면 최근 30분간 조회
KST = timezone(timedelta(hours=9))

# 전역 캐시: 캐릭터ID별로 마지막 처리 시점(datetime 객체) 저장
last_processed_time = {}
last_processed_lock = asyncio.Lock()


def parse_event_date(item):
    try:
        return datetime.strptime(item.get("date", ""), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def get_rarity_color(rarity: str) -> int:
    mapping = {
        "레전더리": 0xFF7800,  # 주황
        "에픽": 0xFFB400,  # 노란
        "태초": 0x58d3dc  # 청록
    }
    return mapping.get(rarity, 0x000000)


def get_covenant_rarity_color(rarity: str) -> int:
    mapping = {
        "레전더리": 0xFF5500,  # 진한 주황
        "에픽": 0xFFD700,  # 골드
        "태초": 0x00F5FF  # 밝은 청록
    }
    return mapping.get(rarity, 0xFFD700)


def _build_description(adventure_name, character_name, item):
    """아이템 코드별 획득 설명 문자열 생성"""
    code = item.get("code")
    data = item.get("data", {})
    item_name = data.get("itemName", "알 수 없음")
    item_rarity = data.get("itemRarity", "알 수 없음")
    base = f"{adventure_name} 모험단의 {character_name} 모험가가"

    def _location(d):
        channel = d.get('channelName')
        channel_no = d.get('channelNo')
        dungeon = d.get('dungeonName')
        ch_str = f" {channel_no}채널" if channel_no is not None else ""
        if channel and dungeon:
            return f" {channel}{ch_str} {dungeon}에서"
        elif channel:
            return f" {channel}{ch_str}에서"
        elif dungeon:
            return f" {dungeon}에서"
        return ""

    _CODE_TEMPLATES = {
        550: lambda d: (
            f"{_location(d)} **서약 던전 드랍**으로 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
        551: lambda d: (
            f" **서약 레이드 카드 보상**으로 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
        552: lambda d: (
            f"{_location(d)} **서약 항아리&상자**로 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
        553: lambda d: (
            f" **서약 업그레이드**로 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
        554: lambda d: (
            f" **서약 제작서**로 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
        555: lambda d: (
            f" **서약 무기고**에서 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
        556: lambda d: (
            f" **초월의 돌**로 서약 초월하여 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
        557: lambda d: (
            f"{_location(d)} **서약 던전 카드 보상**으로 "
            f"**✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
        ),
    }

    template = _CODE_TEMPLATES.get(code)
    suffix = template(data) if template else f" **✦ {item_name}[{item_rarity}] ✦**(을)를 획득했습니다!"
    return base + suffix


def _is_covenant_decision(item) -> bool:
    """아이템 이름에 '결정'이 포함되면 서약 결정, 아니면 빛의 서약(서약 장비)"""
    item_name = item.get("data", {}).get("itemName", "")
    return "결정" in item_name


_COVENANT_TITLES = {
    550: "서약 던전 드랍",
    551: "서약 레이드 보상",
    552: "서약 항아리&상자",
    553: "서약 업그레이드",
    554: "서약 제작서",
    555: "서약 무기고",
    556: "서약 초월",
    557: "서약 던전 카드 보상",
}


def format_item_announce_embed(adventure_name, character_name, item, event_date):
    try:
        dt_pastime = datetime.strptime(event_date, "%Y-%m-%d %H:%M")
        date_str = dt_pastime.strftime("%Y.%m.%d(%H:%M)")
    except ValueError:
        date_str = event_date or "날짜 불명"

    data = item.get("data", {})
    item_rarity = data.get("itemRarity", "알 수 없음")

    description = _build_description(adventure_name, character_name, item)

    code = item.get("code")
    is_decision = _is_covenant_decision(item)

    if is_decision:
        color = get_rarity_color(item_rarity)
    else:
        color = get_covenant_rarity_color(item_rarity)

    embed = discord.Embed(
        description=description,
        color=color
    )
    base_title = _COVENANT_TITLES.get(code, "서약 획득")
    if is_decision:
        embed.title = f"✦ {base_title}! (서약 결정)"
    else:
        embed.title = f"⚡ {base_title}! (빛의 서약)"
    embed.set_footer(text=date_str)
    return embed


def filter_enhance_items(rows: list[dict]) -> list[dict]:
    """강화/증폭 이벤트 중 before >= 10인 것만 필터링 (알림 대상)."""
    return [
        row for row in rows
        if row.get("code") in ENHANCE_CODES
        and (row.get("data", {}).get("before") or 0) >= 10
    ]


def _all_enhance_items(rows: list[dict]) -> list[dict]:
    """강화/증폭 이벤트 전체 반환 (커서 진행용)."""
    return [row for row in rows if row.get("code") in ENHANCE_CODES]


def filter_sealed_lock_items(rows: list[dict]) -> list[dict]:
    """봉인된 자물쇠 이벤트 전체 반환."""
    return [
        row for row in rows
        if row.get("code") in SEALED_LOCK_CODES
    ]


def format_enhance_embed(
    adventure_name: str,
    character_name: str,
    item: dict,
    event_date: str,
) -> discord.Embed:
    """강화(401)/증폭(402) 알림 임베드 생성."""
    try:
        dt = datetime.strptime(event_date, "%Y-%m-%d %H:%M")
        date_str = dt.strftime("%Y.%m.%d(%H:%M)")
    except ValueError:
        date_str = event_date or "날짜 불명"

    data = item.get("data", {})
    code = item.get("code")
    item_name = data.get("itemName", "알 수 없음")
    item_rarity = data.get("itemRarity", "알 수 없음")
    before = data.get("before") or 0
    after = data.get("after") or 0
    result = data.get("result", False) is True
    safe = data.get("safe", False) is True
    ticket = data.get("ticket")

    action = "증폭" if code == 402 else "강화"
    result_text = "성공" if result else "실패"
    if result and after >= 12:
        result_emoji = "🎆"
    elif result:
        result_emoji = "✅"
    elif safe:
        result_emoji = "🛡️"
    else:
        result_emoji = "💥"

    base = f"{adventure_name} 모험단의 {character_name} 모험가가"
    if result:
        change_str = f"**{before}강 → {after}강**"
    else:
        change_str = f"**{before}강**"
    description = (
        f"{base} **{item_name}[{item_rarity}]** {action}에 도전했습니다!\n\n"
        f"{result_emoji} {change_str} ({result_text})"
    )

    if safe:
        description += "\n🛡️ 안전 강화 적용"
    if isinstance(ticket, dict):
        ticket_name = ticket.get("itemName", "알 수 없음")
        description += f"\n🎫 {ticket_name}"

    color = 0x00FF00 if result else 0xFF0000
    title_emoji = "🔨" if result else "💥"

    embed = discord.Embed(
        title=f"{title_emoji} {action} {result_text}! ({before}→{after})",
        description=description,
        color=color,
    )
    embed.set_footer(text=date_str)
    return embed


def format_sealed_lock_embed(
    adventure_name: str,
    character_name: str,
    item: dict,
    event_date: str,
) -> discord.Embed:
    """봉인된 자물쇠(501) 알림 임베드 생성."""
    try:
        dt = datetime.strptime(event_date, "%Y-%m-%d %H:%M")
        date_str = dt.strftime("%Y.%m.%d(%H:%M)")
    except ValueError:
        date_str = event_date or "날짜 불명"

    data = item.get("data", {})
    item_name = data.get("itemName", "알 수 없음")
    booster = data.get("booster", False) is True

    base = f"{adventure_name} 모험단의 {character_name} 모험가가"
    description = f"{base} 봉인된 자물쇠 아이템에서 **🔒 {item_name}**(을)를 획득했습니다!"

    if booster:
        description += "\n\n🎊 **x2 부스터 적용!** 두 배의 행운을 누렸습니다!"

    color = 0xFFD700 if booster else 0x9B59B6

    embed = discord.Embed(
        title="🔒 봉인된 자물쇠 아이템 획득!" + (" 🎊x2!" if booster else ""),
        description=description,
        color=color,
    )
    embed.set_footer(text=date_str)
    return embed


async def _send_enhance_embeds(
    channel: discord.TextChannel,
    items: list[dict],
    adventure_name: str,
    character_name: str,
) -> None:
    """강화/증폭 알림 임베드 발송."""
    for item in items:
        event_date = item.get("date", "")
        embed = format_enhance_embed(adventure_name, character_name, item, event_date)
        await channel.send(embed=embed)


async def _send_sealed_lock_embeds(
    channel: discord.TextChannel,
    items: list[dict],
    adventure_name: str,
    character_name: str,
) -> None:
    """봉인된 자물쇠 알림 임베드 발송."""
    for item in items:
        event_date = item.get("date", "")
        embed = format_sealed_lock_embed(adventure_name, character_name, item, event_date)
        await channel.send(embed=embed)


async def filter_valid_items(timeline_rows):
    valid_items = []
    for row in timeline_rows:
        item_id = row.get("data", {}).get("itemId")
        if not item_id:
            continue
        equip_level = await dnf_api.fetch_item_detail(item_id)
        if equip_level == 115:
            # 타임라인 API의 희귀도가 부정확할 수 있으므로 아이템 API 값으로 보정
            correct_rarity = await dnf_api.get_item_rarity(item_id)
            if correct_rarity:
                row["data"]["itemRarity"] = correct_rarity
            valid_items.append(row)
    return valid_items


async def _sync_character_name(char):
    """DNF API에서 최신 캐릭터 이름 동기화. 변경된 이름 반환."""
    server_id = char['server_id']
    character_id = char['character_id']
    character_name = char['character_name']

    char_details = await dnf_api.get_character_details(server_id, character_id)
    if not char_details:
        return character_name

    api_name = char_details.get('characterName')
    if api_name and api_name != character_name:
        logger.info(f"캐릭터 이름 변경 감지: {character_name} -> {api_name}")
        await update_character_name(character_id, api_name)
        return api_name

    return character_name


def _compute_start_date(last_checked, now):
    """타임라인 조회 시작 시간 계산"""
    if last_checked:
        start_time = datetime.strptime(last_checked, "%Y%m%dT%H%M")
        return start_time.strftime("%Y%m%dT%H%M")
    lookback = now - timedelta(minutes=DEFAULT_LOOKBACK_MINUTES)
    return lookback.strftime("%Y%m%dT%H%M")


def _is_new_event(event_dt, last_time):
    """이벤트가 마지막 처리 시점 이후인지 판별"""
    return last_time is None or event_dt > last_time


def _update_max_time(current_max, event_dt):
    """최대 이벤트 시간 갱신"""
    if event_dt is None:
        return current_max
    return event_dt if (current_max is None or event_dt > current_max) else current_max


def _filter_new_items(filtered_items, last_time):
    """이전 처리 시점 이후의 새 아이템만 필터링. (new_items, max_event_time) 반환."""
    new_filtered_items = []
    max_event_time = last_time

    for item in filtered_items:
        event_dt = parse_event_date(item)
        if event_dt is None or not _is_new_event(event_dt, last_time):
            continue
        new_filtered_items.append(item)
        max_event_time = _update_max_time(max_event_time, event_dt)

    return new_filtered_items, max_event_time


async def _send_item_embeds(channel, filtered_items, adventure_name, character_name):
    """필터링된 아이템들을 채널에 발송"""
    for item in filtered_items:
        event_date = item.get("date", "")
        embed = format_item_announce_embed(adventure_name, character_name, item, event_date)
        await channel.send(embed=embed)


async def _resolve_output_channel(bot, guild_id):
    """아이템 알림 출력 채널 조회. 실패 시 None 반환."""
    channel_id = await get_output_channel(guild_id, 'item')
    if not channel_id:
        logger.warning(f"길드 {guild_id}에 등록된 출력 채널이 없습니다.")
        return None
    channel = bot.get_channel(int(channel_id))
    if not channel:
        logger.warning(f"채널 {channel_id}을 찾을 수 없습니다.")
        return None
    return channel


def _extract_timeline_rows(timeline, character_name):
    """타임라인 응답에서 rows 추출. 실패 시 None."""
    if timeline is None or "timeline" not in timeline:
        logger.warning(f"[{character_name}] 타임라인 데이터를 받아오지 못했습니다.")
        return None
    if "rows" not in timeline["timeline"]:
        logger.warning(f"[{character_name}] 타임라인 데이터를 받아오지 못했습니다.")
        return None
    return timeline["timeline"]["rows"]


async def _process_timeline_items(rows, character_id, last_time):
    """타임라인 rows에서 유효 장비 아이템 필터링 및 새 아이템 분리."""
    # 강화/증폭/봉인된 자물쇠는 별도 파이프라인에서 처리 — 여기서 제외
    equipment_rows = [
        row for row in rows
        if row.get("code") not in ENHANCE_CODES
        and row.get("code") not in SEALED_LOCK_CODES
    ]
    filtered_items = await filter_valid_items(equipment_rows)
    filtered_items = [
        item for item in filtered_items
        if item.get("data", {}).get("itemRarity") in ALLOWED_RARITIES
    ]
    return _filter_new_items(filtered_items, last_time)


async def notify_items_for_character(char, bot, guild_id, semaphore):
    async with semaphore:
        character_id = char['character_id']
        server_id = char['server_id']
        adventure_name = char.get('adventure_name', '모험단명 없음')

        character_name = await _sync_character_name(char)

        last_checked = await get_last_checked(character_id)
        now = datetime.now(KST)
        end_date = now.strftime("%Y%m%dT%H%M")
        start_date = _compute_start_date(last_checked, now)

        timeline = await dnf_api.fetch_timeline(server_id, character_id, start_date=start_date, end_date=end_date)
        rows = _extract_timeline_rows(timeline, character_name)
        if rows is None:
            await update_last_checked(character_id, end_date)
            return

        async with last_processed_lock:
            last_time = last_processed_time.get(character_id)

        filtered_items, max_event_time = await _process_timeline_items(rows, character_id, last_time)

        channel = await _resolve_output_channel(bot, guild_id)
        if not channel:
            return

        covenant_items = [
            item for item in filtered_items
            if item.get("code") in COVENANT_CODES
        ]
        if covenant_items:
            await _send_item_embeds(channel, covenant_items, adventure_name, character_name)

        # --- 강화/증폭 알림 (401/402) ---
        # 커서는 모든 401/402 이벤트에서 진행, 알림은 before>=10만
        _, enhance_cursor_time = _filter_new_items(_all_enhance_items(rows), last_time)
        max_event_time = _update_max_time(max_event_time, enhance_cursor_time)
        new_enhance_items, _ = _filter_new_items(filter_enhance_items(rows), last_time)
        if new_enhance_items:
            await _send_enhance_embeds(channel, new_enhance_items, adventure_name, character_name)

        # --- 봉인된 자물쇠 알림 (501) ---
        sealed_items_raw = filter_sealed_lock_items(rows)
        new_sealed_items, sealed_max_time = _filter_new_items(sealed_items_raw, last_time)
        max_event_time = _update_max_time(max_event_time, sealed_max_time)
        if new_sealed_items:
            await _send_sealed_lock_embeds(channel, new_sealed_items, adventure_name, character_name)

        if max_event_time is not None:
            async with last_processed_lock:
                last_processed_time[character_id] = max_event_time

        await update_last_checked(character_id, end_date)


async def notify_all_characters(bot, guild_id):
    grouped = await get_all_characters_grouped_by_adventure()
    if not grouped:
        logger.info("DB에 등록된 캐릭터가 없습니다.")
        return

    semaphore = asyncio.Semaphore(50)  # 최대 50개 동시 실행 제한

    for _adventure, characters in grouped.items():
        tasks = [notify_items_for_character(char, bot, guild_id, semaphore) for char in characters]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"캐릭터 알림 처리 중 오류: {r}")


async def periodic_notify(bot, guild_id):
    while True:
        logger.info(f"=== DNF 타임라인 주기적 체크 시작: {datetime.now(KST)} ===")
        try:
            await notify_all_characters(bot, guild_id)
        except Exception as e:
            logger.error(f"notify_all_characters 실행 중 오류 발생: {e}")
            logger.error(traceback.format_exc())  # 스택 트레이스 출력
        finally:
            await asyncio.sleep(DEFAULT_PERIOD_SEC)
