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
    save_temp_raid_clear,
    get_adventure_exclusion_status
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


def format_item_announce_embed(adventure_name, character_name, item, event_date):
    dt_pastime = datetime.strptime(event_date, "%Y-%m-%d %H:%M")
    date_str = dt_pastime.strftime("%Y.%m.%d(%H:%M)")

    code = item.get("code")
    data = item.get("data", {})
    item_name = data.get("itemName", "알 수 없음")
    item_rarity = data.get("itemRarity", "알 수 없음")

    color = get_rarity_color(item_rarity)

    description = f"{adventure_name} 모험단의 {character_name} 모험가가"

    if code == 505:  # 던전 드랍
        channel_name = data.get('channelName')
        channel_no = data.get('channelNo')
        dungeon_name = data.get('dungeonName')
        description += f" {channel_name} {channel_no}채널 {dungeon_name}에서 드랍으로 {item_name}[{item_rarity}](을)를 획득했습니다."
    elif code == 513:  # 던전 카드 보상
        dungeon_name = data.get('dungeonName')
        description += f" {dungeon_name}에서 던전 카드 보상으로 {item_name}[{item_rarity}](을)를 획득했습니다."
    elif code == 504:  # 항아리/상자
        channel_name = data.get('channelName')
        channel_no = data.get('channelNo')
        description += f" {channel_name} {channel_no}채널 항아리/상자에서 {item_name}[{item_rarity}](을)를 획득했습니다."
    elif code == 507:  # 레이드 카드 보상
        description += f" 레이드 카드 보상에서 {item_name}[{item_rarity}](을)를 획득했습니다."
    else:
        description += f" {item_name}[{item_rarity}](을)를 획득했습니다."


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


async def notify_items_for_character(char, bot, guild_id, semaphore):
    async with semaphore:
        character_id = char['character_id']
        server_id = char['server_id']
        character_name = char['character_name']
        adventure_name = char.get('adventure_name', '모험단명 없음')

        # === 캐릭터 이름 동기화 ===
        # DNF API에서 최신 캐릭터 정보 조회
        char_details = await dnf_api.get_character_details(server_id, character_id)
        if char_details:
            api_name = char_details.get('characterName')
            if api_name and api_name != character_name:
                logger.info(f"캐릭터 이름 변경 감지: {character_name} -> {api_name}")
                await update_character_name(character_id, api_name)
                character_name = api_name  # 로컬 변수도 업데이트하여 알림에 새 이름 사용
        # ========================

        last_checked = await get_last_checked(character_id)
        now = datetime.now(KST)
        end_date = now.strftime("%Y%m%dT%H%M")

        if last_checked:
            start_time = datetime.strptime(last_checked, "%Y%m%dT%H%M")
            start_date = start_time.strftime("%Y%m%dT%H%M")
        else:
            lookback = now - timedelta(minutes=DEFAULT_LOOKBACK_MINUTES)
            start_date = lookback.strftime("%Y%m%dT%H%M")

        timeline = await dnf_api.fetch_timeline(server_id, character_id, start_date=start_date, end_date=end_date)
        if timeline is None or "timeline" not in timeline or "rows" not in timeline["timeline"]:
            logger.warning(f"[{character_name}] 타임라인 데이터를 받아오지 못했습니다.")
            await update_last_checked(character_id, end_date)
            return

        rows = timeline["timeline"]["rows"]
        filtered_items = await filter_valid_items(rows)

        # 레전더리 아이템 제외 필터링
        filtered_items = [
            item for item in filtered_items
            if item.get("data", {}).get("itemRarity") in ALLOWED_RARITIES
        ]

        # 이전 처리 시점 락을 걸고 읽기
        async with last_processed_lock:
            last_time = last_processed_time.get(character_id)

        new_filtered_items = []
        max_event_time = last_time  # 이번에 처리한 가장 최신 시간 추적

        for item in filtered_items:
            event_dt = parse_event_date(item)
            if event_dt is None:
                continue
            if (last_time is None) or (event_dt > last_time):
                new_filtered_items.append(item)
                if (max_event_time is None) or (event_dt > max_event_time):
                    max_event_time = event_dt

        filtered_items = new_filtered_items

        # 디스코드 채널 조회
        channel_id = await get_output_channel(guild_id)
        if not channel_id:
            logger.warning(f"길드 {guild_id}에 등록된 출력 채널이 없습니다.")
            return
        channel = bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"채널 {channel_id}을 찾을 수 없습니다.")
            return

        if filtered_items:
            for item in filtered_items:
                event_date = item.get("date", "")
                embed = format_item_announce_embed(adventure_name, character_name, item, event_date)
                await channel.send(embed=embed)

        # 처리 완료한 가장 최신 시간 캐싱도 락 걸고 쓰기
        if max_event_time is not None:
            async with last_processed_lock:
                last_processed_time[character_id] = max_event_time

        await update_last_checked(character_id, end_date)
        
        # === 레이드 클리어 체크 ===
        await check_raid_clears(char, timeline)


async def check_raid_clears(char, timeline_data):
    """레이드 클리어 체크 (code 201, 악연 필터링)"""
    if not timeline_data or "timeline" not in timeline_data:
        return
    
    # 던담검색제외된 모험단이면 레이드 클리어도 제외
    adventure_name = char.get('adventure_name', '')
    server_id = char.get('server_id', '')
    
    if adventure_name and server_id:
        is_excluded = await get_adventure_exclusion_status(adventure_name, server_id)
        if is_excluded:
            logger.info(f"제외된 모험단 레이드 클리어 무시: {adventure_name}")
            return
    
    rows = timeline_data.get("timeline", {}).get("rows", [])
    
    for item in rows:
        if item.get("code") != 201:
            continue
        
        data = item.get("data", {})
        raid_name = data.get("raidName", "")
        mode_name = data.get("modeName", "")
        
        # "악연" 필터링
        if "악연" not in raid_name and "악연" not in mode_name:
            continue
        
        # 임시 클리어 저장
        clear_info = {
            "character_id": char['character_id'],
            "character_name": char['character_name'],
            "adventure_name": char.get('adventure_name', '알 수 없음'),
            "raid_party_name": data.get("raidPartyName", "알 수 없음"),
            "clear_date": item.get("date", ""),
            "raid_name": raid_name,
            "mode_name": mode_name
        }
        
        logger.info(f"악연 클리어 감지: {char['character_name']} - {clear_info['raid_party_name']}")
        await save_temp_raid_clear(clear_info)


async def notify_all_characters(bot, guild_id):
    grouped = await get_all_characters_grouped_by_adventure()
    if not grouped:
        logger.info("DB에 등록된 캐릭터가 없습니다.")
        return

    semaphore = asyncio.Semaphore(50)  # 최대 50개 동시 실행 제한

    async with aiohttp.ClientSession():
        for adventure, characters in grouped.items():
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
