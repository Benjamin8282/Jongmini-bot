from .daily_aggregation import aggregate_items_and_notify_for_period
from core.logger import logger
from core.time_utils import get_weekly_period

async def aggregate_weekly_items_and_notify(bot, guild_id):
    """
    주간 집계 (목요일 06:00 ~ 현재 시각)
    """
    start_time, end_time = get_weekly_period()
    await aggregate_items_and_notify_for_period(bot, guild_id, start_time, end_time, base_time=end_time, period="주간")
    logger.info("주간 모험단 아이템 집계 및 알림 완료")
