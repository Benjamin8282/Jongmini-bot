import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from core import dnf_api
from core.db import (
    get_all_characters_grouped_by_adventure,
    get_output_channel,
    get_last_aggregation_time,
    update_last_aggregation_time
)
from core.logger import logger
import discord

from core.models import RARITY_WEIGHTS

KST = timezone(timedelta(hours=9))

MAX_RETRY_DURATION = 7 * 60 * 60  # 7시간
RETRY_INTERVAL = 60  # 1분
CONCURRENT_REQUEST_LIMIT = 10  # 동시 요청 제한
MAX_ITEM_CONCURRENT = 20  # 아이템 레벨 조회 동시 제한

async def fetch_character_timeline_all_with_long_retry(server_id, character_id, start_date, end_date):
    start_time = datetime.now().timestamp()
    while True:
        try:
            result = await dnf_api.fetch_timeline_with_pagination(server_id, character_id, start_date, end_date)
            if result is not None:
                return result
            logger.warning(f"[{character_id}] API null 응답, 재시도 중...")
        except Exception as e:
            logger.warning(f"[{character_id}] API 호출 예외: {e}, 재시도 중...")

        if datetime.now().timestamp() - start_time > MAX_RETRY_DURATION:
            logger.error(f"[{character_id}] 최대 재시도 시간 초과, 실패 처리")
            return None

        await asyncio.sleep(RETRY_INTERVAL)

async def filter_items_level_115(items):
    semaphore = asyncio.Semaphore(MAX_ITEM_CONCURRENT)

    async def check_item_level(item):
        item_id = item.get("data", {}).get("itemId")
        if not item_id:
            return None
        async with semaphore:
            level = await dnf_api.fetch_item_detail(item_id)
            if level == 115:
                return item
        return None

    results = await asyncio.gather(*(check_item_level(item) for item in items))
    return [item for item in results if item is not None]

def format_rank_embed(rank_list, timestamp):
    embed = discord.Embed(
        title="모험단 일간 아이템 획득량 순위",
        description=f"기준 시각: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        color=0x00ff00
    )
    for i, entry in enumerate(rank_list, start=1):
        counts = entry["counts"]
        line = (f"점수: {entry['score']} "
                f"(태초:{counts.get('태초', 0)}, 에픽:{counts.get('에픽', 0)}, 레전더리:{counts.get('레전더리', 0)})")
        embed.add_field(name=f"{i}위 {entry['adventure_name']}", value=line, inline=False)
    return embed

async def aggregate_daily_items_and_notify(bot, guild_id):
    now = datetime.now(KST)
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    start_time = today_6am - timedelta(days=1)  # 전날 6시
    end_time = today_6am - timedelta(seconds=1)  # 오늘 5시 59분 59초

    start_date_str = start_time.strftime("%Y%m%dT%H%M")
    end_date_str = end_time.strftime("%Y%m%dT%H%M")

    grouped = await get_all_characters_grouped_by_adventure()
    if not grouped:
        logger.info("DB에 등록된 캐릭터가 없습니다.")
        return

    adventure_item_counts = defaultdict(lambda: defaultdict(int))
    semaphore = asyncio.Semaphore(CONCURRENT_REQUEST_LIMIT)  # 동시 캐릭터 처리 제한

    async def process_character(char, adventure_name):
        server_id = char["server_id"]
        character_id = char["character_id"]
        async with semaphore:
            timeline_data = await fetch_character_timeline_all_with_long_retry(
                server_id, character_id, start_date_str, end_date_str
            )
            if not timeline_data:
                logger.warning(f"{char['character_name']} 타임라인 조회 실패")
                return
            rows = timeline_data.get("timeline", {}).get("rows", [])

            # 115레벨 필터링 최적화된 호출
            filtered_rows = await filter_items_level_115(rows)

            for item in filtered_rows:
                rarity = item.get("data", {}).get("itemRarity")
                if rarity in RARITY_WEIGHTS:
                    adventure_item_counts[adventure_name][rarity] += 1

    tasks = [
        process_character(char, adventure_name)
        for adventure_name, characters in grouped.items()
        for char in characters
    ]

    await asyncio.gather(*tasks)

    adventure_scores = []
    for adventure_name, counts in adventure_item_counts.items():
        score = sum(RARITY_WEIGHTS.get(r, 0) * c for r, c in counts.items())
        adventure_scores.append({
            "adventure_name": adventure_name,
            "score": score,
            "counts": counts
        })

    adventure_scores.sort(key=lambda x: x["score"], reverse=True)

    channel_id = await get_output_channel(guild_id)
    if not channel_id:
        logger.warning(f"길드 {guild_id}에 등록된 출력 채널이 없습니다.")
        return
    channel = bot.get_channel(int(channel_id))
    if not channel:
        logger.warning(f"채널 {channel_id}을 찾을 수 없습니다.")
        return

    embed = format_rank_embed(adventure_scores, now)
    await channel.send(embed=embed)
    logger.info("모험단 일간 획득량 순위 Discord에 전송 완료")

    await update_last_aggregation_time(now.strftime("%Y%m%dT%H%M"))

async def wait_until_next_6am():
    now = datetime.now(KST)
    next_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now >= next_6am:
        next_6am += timedelta(days=1)
    wait_seconds = (next_6am - now).total_seconds()
    logger.info(f"다음 6시까지 대기: {wait_seconds}초")
    await asyncio.sleep(wait_seconds)

async def daily_aggregation_task(bot, guild_id):
    while True:
        last_agg_time_str = await get_last_aggregation_time()
        now = datetime.now(KST)
        today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)

        if last_agg_time_str:
            last_agg_time = datetime.strptime(last_agg_time_str, "%Y%m%dT%H%M").replace(tzinfo=KST)
        else:
            last_agg_time = None

        if last_agg_time is None or last_agg_time < today_6am <= now:
            logger.info("봇 부팅 후 최초 집계 또는 미실행 집계 감지, 즉시 실행")
            await aggregate_daily_items_and_notify(bot, guild_id)

        await wait_until_next_6am()
        logger.info("6시 정각 집계 작업 실행")
        await aggregate_daily_items_and_notify(bot, guild_id)
