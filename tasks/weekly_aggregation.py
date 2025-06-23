from datetime import datetime, timedelta, timezone

from .daily_aggregation import aggregate_items_and_notify_for_period
from core.logger import logger

KST = timezone(timedelta(hours=9))

async def aggregate_weekly_items_and_notify(bot, guild_id):
    """
    주간 집계 (목요일 06:00 ~ 현재 시각)
    """
    now = datetime.now(KST)
    weekday = now.weekday()  # 월=0, 목=3

    days_since_thursday = (weekday - 3) % 7
    last_thursday = now - timedelta(days=days_since_thursday)
    start_time = last_thursday.replace(hour=6, minute=0, second=0, microsecond=0)

    # 만약 현재가 목요일 6시 이전이면 이전 주 목요일 6시로 조정
    if now < start_time:
        start_time -= timedelta(days=7)

    end_time = now

    await aggregate_items_and_notify_for_period(bot, guild_id, start_time, end_time, base_time=end_time, period="주간")
    logger.info("주간 모험단 아이템 집계 및 알림 완료")
