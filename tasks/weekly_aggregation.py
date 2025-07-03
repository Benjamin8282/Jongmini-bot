import asyncio
from datetime import datetime, timedelta

from .daily_aggregation import aggregate_items_and_notify_for_period
from core.logger import logger
from core.time_utils import get_weekly_period, KST


async def aggregate_weekly_items_and_notify(bot, guild_id):
    """
    주간 집계 (목요일 06:00 ~ 현재 시각)
    """
    start_time, end_time = get_weekly_period()
    await aggregate_items_and_notify_for_period(bot, guild_id, start_time, end_time, base_time=end_time, period="주간")
    logger.info("주간 모험단 아이템 집계 및 알림 완료")


async def wait_until_next_thursday_6am():
    now = datetime.now(KST)
    # weekday() Monday is 0 and Sunday is 6. Thursday is 3.
    days_until_thursday = (3 - now.weekday() + 7) % 7
    next_thursday = now + timedelta(days=days_until_thursday)
    next_run_time = next_thursday.replace(hour=6, minute=0, second=0, microsecond=0)

    if now >= next_run_time:
        # If it's already past 6am on Thursday, wait for next week's Thursday.
        next_run_time += timedelta(weeks=1)

    wait_seconds = (next_run_time - now).total_seconds()
    logger.info(f"다음 주간 집계(목요일 6시)까지 대기: {wait_seconds:.0f}초")
    await asyncio.sleep(wait_seconds)


async def weekly_aggregation_task(bot, guild_id):
    """
    매주 목요일 6시 정기 집계 주기 작업
    """
    while True:
        await wait_until_next_thursday_6am()
        logger.info("목요일 6시 정각 주간 집계 작업 실행")
        await aggregate_weekly_items_and_notify(bot, guild_id)
