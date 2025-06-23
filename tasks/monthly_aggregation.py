from datetime import datetime, timedelta, timezone

from .daily_aggregation import aggregate_items_and_notify_for_period
from core.logger import logger

KST = timezone(timedelta(hours=9))

async def aggregate_monthly_items_and_notify(bot, guild_id):
    """
    월간 집계 (매월 1일 06:00 ~ 현재 시각)
    """
    now = datetime.now(KST)
    month_start = now.replace(day=1, hour=6, minute=0, second=0, microsecond=0)

    # 현재 시각이 1일 6시 이전이면 이전 달 1일 6시로 조정
    if now < month_start:
        year = now.year
        month = now.month - 1
        if month == 0:
            month = 12
            year -= 1
        month_start = month_start.replace(year=year, month=month)

    start_time = month_start
    end_time = now

    await aggregate_items_and_notify_for_period(bot, guild_id, start_time, end_time, base_time=end_time, period="월간")
    logger.info("월간 모험단 아이템 집계 및 알림 완료")
