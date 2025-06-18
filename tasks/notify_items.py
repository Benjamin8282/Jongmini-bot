import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
import discord

from core import dnf_api
from core.db import (
    get_all_characters_grouped_by_adventure,
    get_last_checked, update_last_checked,
    get_output_channel
)

from core.logger import logger
from core.models import SERVER_MAP  # 서버명 매핑용

DEFAULT_PERIOD_MINUTES = 3
DEFAULT_LOOKBACK_MINUTES = 30  # 기록 없으면 최근 30분간 조회
KST = timezone(timedelta(hours=9))

def get_rarity_color(rarity: str) -> int:
    # 등급별 16진수 색상을 int로 반환
    mapping = {
        "레전더리": 0xFF7800,  # 주황
        "에픽": 0xFFB400,      # 노란
        "태초": 0x58d3dc       # 청록
    }
    return mapping.get(rarity, 0x000000)  # 기본 검정

def format_item_announce_embed(adventure_name, character_name, item_name, item_rarity, event_date):
    import datetime
    dt = datetime.datetime.strptime(event_date, "%Y-%m-%d %H:%M")
    date_str = dt.strftime("%Y.%m.%d(%H:%M)")

    color = get_rarity_color(item_rarity)

    embed = discord.Embed(
        description=f"{adventure_name} 모험단의 {character_name} 모험가가 {item_name}[{item_rarity}](을)를 획득했습니다.",
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

# ... 기존 코드 유지 ...

async def notify_items_for_character(session, char, bot, guild_id):
    character_id = char['character_id']
    server_id = char['server_id']
    character_name = char['character_name']
    adventure_name = char.get('adventure_name', '모험단명 없음')

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
        if item.get("data", {}).get("itemRarity") in ("에픽", "태초")
    ]

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
            data = item.get("data", {})
            item_name = data.get("itemName", "알 수 없음")
            item_rarity = data.get("itemRarity", "알 수 없음")
            event_date = item.get("date", "")
            embed = format_item_announce_embed(adventure_name, character_name, item_name, item_rarity, event_date)
            await channel.send(embed=embed)

    await update_last_checked(character_id, end_date)


async def notify_all_characters(bot, guild_id):
    grouped = await get_all_characters_grouped_by_adventure()
    if not grouped:
        logger.info("DB에 등록된 캐릭터가 없습니다.")
        return

    async with aiohttp.ClientSession() as session:
        for adventure, characters in grouped.items():
            for char in characters:
                await notify_items_for_character(session, char, bot, guild_id)

async def periodic_notify(bot, guild_id):
    while True:
        logger.info(f"=== DNF 타임라인 주기적 체크 시작: {datetime.now(KST)} ===")
        await notify_all_characters(bot, guild_id)
        await asyncio.sleep(DEFAULT_PERIOD_MINUTES * 60)
