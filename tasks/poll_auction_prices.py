import asyncio
import traceback

from core.db import (
    get_all_watch_items,
    save_auction_prices,
)
from core.dnf_api import fetch_auction_sold
from core.logger import logger
from tasks.price_alert import process_alerts_for_item, process_user_alerts_for_item

DEFAULT_POLL_INTERVAL = 30  # 30초


async def fetch_and_save_item_prices(item_id: str, item_name: str) -> int:
    """단일 아이템의 경매장 시세를 조회하여 DB에 저장. 저장된 건수 반환."""
    sold_data = await fetch_auction_sold(item_name)
    if not sold_data:
        return 0

    records = [
        {
            "item_id": item_id,
            "sold_date": row["soldDate"],
            "unit_price": row["unitPrice"],
            "price": row["price"],
            "count": row["count"]
        }
        for row in sold_data
        if row.get("itemId") == item_id
    ]
    if records:
        await save_auction_prices(records)
        logger.info(f"시세 수집 완료: {item_name} - {len(records)}건")
    return len(records)


async def _process_single_item(bot, guild_id, item):
    """단일 아이템의 시세 수집 및 알림 처리"""
    try:
        await fetch_and_save_item_prices(item["item_id"], item["item_name"])
        if bot and guild_id:
            await process_alerts_for_item(
                bot, guild_id,
                item["item_id"], item["item_name"],
                registered_at=item.get("registered_at")
            )
            await process_user_alerts_for_item(
                bot, item["item_id"], item["item_name"]
            )
    except Exception as e:
        logger.error(f"아이템 '{item.get('item_name', '?')}' 폴링 오류: {e}")


async def _poll_once(bot, guild_id):
    """감시 아이템 1회 폴링"""
    watch_items = await get_all_watch_items()
    if not watch_items:
        logger.info("시세 감시 대상 아이템 없음, 스킵")
        return

    for item in watch_items:
        await _process_single_item(bot, guild_id, item)


async def poll_auction_prices(bot=None, guild_id=None):
    """등록된 감시 아이템들의 경매장 시세를 주기적으로 폴링 (거래 이력 영구 보존)"""
    while True:
        try:
            await _poll_once(bot, guild_id)
        except Exception as e:
            logger.error(f"경매장 시세 폴링 오류: {e}")
            logger.error(traceback.format_exc())
        finally:
            await asyncio.sleep(DEFAULT_POLL_INTERVAL)
