from .daily_aggregation import aggregate_items_and_notify_for_period
from core.logger import logger
from core.time_utils import get_monthly_period

async def aggregate_monthly_items_and_notify(bot, guild_id):
    """
    월간 집계 (매월 1일 06:00 ~ 현재 시각)
    """
    start_time, end_time = get_monthly_period()
    await aggregate_items_and_notify_for_period(bot, guild_id, start_time, end_time, base_time=end_time, period="월간")
    logger.info("월간 모험단 아이템 집계 및 알림 완료")
