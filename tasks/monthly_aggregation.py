import asyncio
from datetime import datetime, timedelta

from .daily_aggregation import aggregate_items_and_notify_for_period
from core.logger import logger
from core.time_utils import get_monthly_period, KST


async def aggregate_monthly_items_and_notify(bot, guild_id):
    """
    월간 집계 (매월 1일 06:00 ~ 현재 시각)
    """
    start_time, end_time = get_monthly_period()
    await aggregate_items_and_notify_for_period(bot, guild_id, start_time, end_time, base_time=end_time, period="월간")
    logger.info("월간 모험단 아이템 집계 및 알림 완료")


async def wait_until_next_month_1st_6am():
    now = datetime.now(KST)
    # Calculate the first day of the next month
    if now.month == 12:
        next_month_first_day = now.replace(year=now.year + 1, month=1, day=1)
    else:
        next_month_first_day = now.replace(month=now.month + 1, day=1)

    next_run_time = next_month_first_day.replace(hour=6, minute=0, second=0, microsecond=0)

    if now >= next_run_time:
        # If it's already past 6am on the 1st, aim for the next month's 1st.
        # This logic might need adjustment based on when the check runs.
        # A simple addition of a month might not be safe due to varying days in months.
        if next_run_time.month == 12:
            next_run_time = next_run_time.replace(year=next_run_time.year + 1, month=1)
        else:
            next_run_time = next_run_time.replace(month=next_run_time.month + 1)

    wait_seconds = (next_run_time - now).total_seconds()
    logger.info(f"다음 월간 집계(1일 6시)까지 대기: {wait_seconds:.0f}초")
    await asyncio.sleep(wait_seconds)


async def monthly_aggregation_task(bot, guild_id):
    """
    매월 1일 6시 정기 집계 주기 작업
    """
    while True:
        await wait_until_next_month_1st_6am()
        logger.info("매월 1일 6시 정각 월간 집계 작업 실행")
        await aggregate_monthly_items_and_notify(bot, guild_id)
