import asyncio
from collections import defaultdict

from core.db import (
    get_recent_temp_clears,
    clear_temp_raid_clears,
    get_raid_rank,
    save_raid_first_clear,
    get_output_channel
)
from core.logger import logger
import discord


async def process_raid_first_clears_task(bot, guild_id):
    """15초마다 임시 클리어를 처리하여 순위 계산"""
    while True:
        await asyncio.sleep(15)  # 15초마다 실행

        logger.info("=== 레이드 퍼스트 클리어 처리 시작 ===")

        try:
            # 최근 1분 내 클리어 조회
            clears = await get_recent_temp_clears(minutes=1)

            if not clears:
                logger.info("처리할 임시 클리어 없음")
                continue

            # 악연 클리어만 필터링
            akyeon_clears = [
                c for c in clears
                if "악연" in c.get('raid_name', '') or "악연" in c.get('mode_name', '')
            ]

            if not akyeon_clears:
                logger.info("악연 클리어 없음, 임시 데이터 삭제")
                await clear_temp_raid_clears()
                continue

            logger.info(f"악연 클리어 {len(akyeon_clears)}개 발견")

            # 공격대별 그룹핑
            party_groups = defaultdict(list)
            for clear in akyeon_clears:
                party_name = clear['raid_party_name']
                party_groups[party_name].append(clear)

            # 순위 계산
            party_ranks = []
            for party_name, members in party_groups.items():
                # 각 공격대의 가장 이른 클리어 시각
                earliest = min(m['clear_date'] for m in members)
                party_ranks.append({
                    'party_name': party_name,
                    'clear_time': earliest,
                    'members': members
                })

            # 시각으로 정렬
            party_ranks.sort(key=lambda x: x['clear_time'])

            # 기존 순위 확인
            existing = await get_raid_rank("diregie_akyeon")

            # 새로운 1/2/3위 확인 및 축하 메시지
            for rank, party in enumerate(party_ranks[:3], 1):
                if not is_already_recorded(existing, rank, party):
                    await send_first_clear_message(bot, guild_id, rank, party)
                    await save_raid_first_clear("diregie_akyeon", rank, party)

            # 처리된 임시 클리어 삭제
            await clear_temp_raid_clears()
            logger.info("레이드 퍼스트 클리어 처리 완료")

        except Exception as e:
            logger.error(f"레이드 클리어 처리 중 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())


def is_already_recorded(existing: dict | None, rank: int, party_info: dict) -> bool:
    """이미 기록된 순위인지 확인"""
    if not existing:
        return False

    rank_fields = {
        1: ('first_party_name', 'first_clear_date'),
        2: ('second_party_name', 'second_clear_date'),
        3: ('third_party_name', 'third_clear_date')
    }

    party_field, date_field = rank_fields[rank]

    # 같은 공격대 이름과 시각이면 이미 기록됨
    return (existing.get(party_field) == party_info['party_name'] and
            existing.get(date_field) == party_info['clear_time'])


async def send_first_clear_message(bot, guild_id, rank, party_info):
    """퍼스트 클리어 축하 메시지"""

    channel_id = await get_output_channel(guild_id)
    if not channel_id:
        logger.warning(f"길드 {guild_id}에 등록된 출력 채널이 없습니다.")
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        logger.warning(f"채널 {channel_id}을 찾을 수 없습니다.")
        return

    # @here 멘션
    await channel.send("@here")

    # 순위별 색상
    colors = {1: 0xFFD700, 2: 0xC0C0C0, 3: 0xCD7F32}
    emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
    titles = {1: "퍼스트", 2: "세컨드", 3: "써드"}

    # 멤버 정보가 dict 리스트일 수도 있고 이미 파싱된 형태일 수도 있음
    members = party_info['members']
    members_text = "\n".join([
        f"• {m.get('adventure_name', '알 수 없음')} - {m.get('character_name', '알 수 없음')}"
        for m in members
    ])

    embed = discord.Embed(
        title=f"🎊 {emojis[rank]} 디레지에 악연 {titles[rank]} 클리어! {emojis[rank]} 🎊",
        description=(
            f"**공격대**: {party_info['party_name']}\n"
            f"**클리어 시각**: {party_info['clear_time']}\n\n"
            f"**참여 멤버**:\n{members_text}"
        ),
        color=colors[rank]
    )

    await channel.send(embed=embed)
    logger.info(f"{rank}위 축하 메시지 전송 완료")
