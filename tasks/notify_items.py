import asyncio
from datetime import datetime, timedelta, timezone
import traceback  # traceback 모듈 추가

import aiohttp
import discord

from core import dnf_api
from core.db import (
    get_all_characters_grouped_by_adventure,
    get_last_checked, update_last_checked,
    get_output_channel,
    update_character_name,
)

from core.logger import logger
from core.models import ALLOWED_RARITIES  # 서버명 매핑용

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
    # 등급별 16진수 색상을 int로 반환
    mapping = {
        "레전더리": 0xFF7800,  # 주황
        "에픽": 0xFFB400,  # 노란
        "태초": 0x58d3dc  # 청록
    }
    return mapping.get(rarity, 0x000000)  # 기본 검정


def _build_description(adventure_name, character_name, item):
    """아이템 코드별 획득 설명 문자열 생성"""
    code = item.get("code")
    data = item.get("data", {})
    item_name = data.get("itemName", "알 수 없음")
    item_rarity = data.get("itemRarity", "알 수 없음")
    base = f"{adventure_name} 모험단의 {character_name} 모험가가"

    _CODE_TEMPLATES = {
        505: lambda d: (
            f" {d.get('channelName')} {d.get('channelNo')}채널 "
            f"{d.get('dungeonName')}에서 드랍으로 {item_name}[{item_rarity}](을)를 획득했습니다."
        ),
        513: lambda d: (
            f" {d.get('dungeonName')}에서 던전 카드 보상으로 {item_name}[{item_rarity}](을)를 획득했습니다."
        ),
        504: lambda d: (
            f" {d.get('channelName')} {d.get('channelNo')}채널 "
            f"항아리/상자에서 {item_name}[{item_rarity}](을)를 획득했습니다."
        ),
        507: lambda d: f" 레이드 카드 보상에서 {item_name}[{item_rarity}](을)를 획득했습니다.",
    }

    template = _CODE_TEMPLATES.get(code)
    suffix = template(data) if template else f" {item_name}[{item_rarity}](을)를 획득했습니다."
    return base + suffix


def format_item_announce_embed(adventure_name, character_name, item, event_date):
    dt_pastime = datetime.strptime(event_date, "%Y-%m-%d %H:%M")
    date_str = dt_pastime.strftime("%Y.%m.%d(%H:%M)")

    data = item.get("data", {})
    item_rarity = data.get("itemRarity", "알 수 없음")
    color = get_rarity_color(item_rarity)

    description = _build_description(adventure_name, character_name, item)

    embed = discord.Embed(
        description=description,
        color=color
    )
    embed.set_footer(text=date_str)
    return embed


async def filter_valid_items(timeline_rows):
    valid_items = []
    for row in timeline_rows:
        item_id = row.get("data", {}).get("itemId")
        if not item_id:
            continue
        equip_level = await dnf_api.fetch_item_detail(item_id)
        if equip_level == 115:
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
    """타임라인 rows에서 유효 아이템 필터링 및 새 아이템 분리"""
    filtered_items = await filter_valid_items(rows)
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

        if filtered_items:
            await _send_item_embeds(channel, filtered_items, adventure_name, character_name)

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

    async with aiohttp.ClientSession():
        for _adventure, characters in grouped.items():
            tasks = [notify_items_for_character(char, bot, guild_id, semaphore) for char in characters]
            await asyncio.gather(*tasks)


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
