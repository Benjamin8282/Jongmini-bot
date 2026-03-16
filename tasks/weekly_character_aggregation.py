from datetime import datetime, timedelta, timezone
from collections import defaultdict

from core.db import get_all_characters, get_output_channel  # 캐릭터 목록 조회 함수
from core.logger import logger
from core.models import RARITY_WEIGHTS
from core.dnf_api import fetch_timeline, fetch_item_detail
import discord
import asyncio

KST = timezone(timedelta(hours=9))
MAX_CONCURRENT_REQUESTS = 50  # 병렬 요청 제한


async def filter_items_level_115(timeline_rows):
    """
    아이템 레벨 115 필터링 (비동기 병렬 처리)
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def check_item_level(item):
        item_id = item.get("data", {}).get("itemId")
        if not item_id:
            return None
        async with semaphore:
            level = await fetch_item_detail(item_id)
            if level == 115:
                return item
        return None

    results = await asyncio.gather(*(check_item_level(item) for item in timeline_rows))
    return [item for item in results if item is not None]


def format_character_rank_embed(rank_list, timestamp):
    embed = discord.Embed(
        title="캐릭터별 주간 아이템 획득량 순위",
        description=f"기준 시각: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        color=0x0099ff
    )
    prev_score = None
    prev_rank = 0
    count_same_score = 0  # 현재까지 동점자 수

    display_list = rank_list[:20]

    for entry in display_list:
        score = entry['score']
        counts = entry['counts']
        character_name = entry['character_name']
        adventure_name = entry.get('adventure_name', '모험단 없음')

        if score == prev_score:
            # 동점자: 순위 유지, 동점자 수 증가
            rank = prev_rank
            count_same_score += 1
        else:
            # 점수 다르면 이전 순위 + 동점자 수 + 1
            rank = prev_rank + count_same_score + 1
            count_same_score = 0
            prev_score = score
            prev_rank = rank

        line = (f"점수: {score} "
                f"(태초:{counts.get('태초', 0)}, 에픽:{counts.get('에픽', 0)}, 레전더리:{counts.get('레전더리', 0)})")
        embed.add_field(name=f"{rank}위 {character_name} ({adventure_name})", value=line, inline=False)

    return embed


def _compute_weekly_period(now):
    """주간 집계 기간 계산. (start_time, end_time) 반환."""
    weekday = now.weekday()
    days_since_thursday = (weekday - 3) % 7
    last_thursday = now - timedelta(days=days_since_thursday)
    start_time = last_thursday.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < start_time:
        start_time -= timedelta(days=7)
    return start_time, now


def _build_rank_list(character_item_counts, characters):
    """캐릭터별 아이템 카운트에서 순위 리스트 생성"""
    # 캐릭터명 -> 모험단명 매핑 생성
    adventure_map = {
        char['character_name']: char.get('adventure_name', '모험단 없음')
        for char in characters
    }

    rank_list = []
    for character_name, counts in character_item_counts.items():
        score = sum(RARITY_WEIGHTS.get(r, 0) * c for r, c in counts.items())
        rank_list.append({
            "character_name": character_name,
            "score": score,
            "counts": counts,
            "adventure_name": adventure_map.get(character_name, '모험단 없음')
        })

    rank_list.sort(key=lambda x: x["score"], reverse=True)
    return rank_list


async def _send_embed_result(bot, guild_id, embed, interaction):
    """embed를 interaction 또는 출력 채널로 전송"""
    if interaction is not None:
        try:
            await interaction.response.send_message(embed=embed)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(embed=embed)
        return

    channel_id = await get_output_channel(guild_id, 'item')
    if not channel_id:
        logger.warning(f"길드 {guild_id}에 등록된 출력 채널이 없습니다.")
        return
    channel = bot.get_channel(int(channel_id))
    if not channel:
        logger.warning(f"채널 {channel_id}을 찾을 수 없습니다.")
        return
    await channel.send(embed=embed)


async def aggregate_weekly_items_by_character(bot, guild_id, interaction=None):
    """
    캐릭터별 주간 아이템 획득량 집계 및 Discord 알림
    """
    now = datetime.now(KST)
    start_time, end_time = _compute_weekly_period(now)

    start_date_str = start_time.strftime("%Y%m%dT%H%M")
    end_date_str = end_time.strftime("%Y%m%dT%H%M")

    characters = await get_all_characters()
    if not characters:
        logger.info("DB에 등록된 캐릭터가 없습니다.")
        return

    character_item_counts = defaultdict(lambda: defaultdict(int))
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def process_character(char):
        async with semaphore:
            server_id = char["server_id"]
            character_id = char["character_id"]
            character_name = char["character_name"]

            timeline = await fetch_timeline(server_id, character_id, start_date=start_date_str, end_date=end_date_str)
            if timeline is None or "timeline" not in timeline or "rows" not in timeline["timeline"]:
                logger.warning(f"{character_name} 타임라인 조회 실패")
                return

            rows = timeline["timeline"]["rows"]
            filtered_items = await filter_items_level_115(rows)

            for item in filtered_items:
                rarity = item.get("data", {}).get("itemRarity")
                if rarity in RARITY_WEIGHTS:
                    character_item_counts[character_name][rarity] += 1

    await asyncio.gather(*(process_character(char) for char in characters))

    rank_list = _build_rank_list(character_item_counts, characters)
    embed = format_character_rank_embed(rank_list, end_time)

    await _send_embed_result(bot, guild_id, embed, interaction)
    logger.info("캐릭터별 주간 아이템 획득량 순위 Discord에 전송 완료")
