import asyncio
import traceback
from datetime import datetime, timedelta, timezone

from core.db import (
    get_all_watch_items,
    save_auction_prices,
    update_watch_item_name,
)
from core.dnf_api import fetch_auction_sold, fetch_item_name
from core.logger import logger
from tasks.price_alert import process_alerts_for_item, process_user_alerts_for_item

DEFAULT_POLL_INTERVAL = 30  # 30초
_NAME_SYNC_INTERVAL = timedelta(hours=1)
_KST = timezone(timedelta(hours=9))

# item_id → 마지막 이름 동기화 시각 (불필요한 API 호출 방지)
_last_name_sync: dict[str, datetime] = {}


async def fetch_and_save_item_prices(item_id: str, item_name: str) -> int | None:
    """단일 아이템의 경매장 시세를 조회하여 DB에 저장.
    저장 건수 반환. API 호출 자체가 실패하면 None 반환."""
    sold_data = await fetch_auction_sold(item_name)
    if sold_data is None:
        return None

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


def _should_sync_name(item_id: str) -> bool:
    """이름 동기화 쿨다운 체크 (1시간 간격)"""
    last = _last_name_sync.get(item_id)
    return last is None or datetime.now(_KST) - last >= _NAME_SYNC_INTERVAL


async def _sync_item_name(item: dict) -> dict:
    """API에서 현재 이름 확인, 변경 시 DB 업데이트. 최신 item dict 반환."""
    _last_name_sync[item["item_id"]] = datetime.now(_KST)
    current_name = await fetch_item_name(item["item_id"])
    if current_name and current_name != item["item_name"]:
        logger.info(f"아이템 이름 변경 감지: {item['item_name']} → {current_name}")
        await update_watch_item_name(item["item_id"], current_name)
        return {**item, "item_name": current_name}
    return item


async def _process_single_item(bot, guild_id, item):
    """단일 아이템의 시세 수집 및 알림 처리"""
    try:
        count = await fetch_and_save_item_prices(item["item_id"], item["item_name"])
        # API 성공 + 0건일 때만 이름 변경 체크 (쿨다운 적용)
        if count == 0 and _should_sync_name(item["item_id"]):
            updated = await _sync_item_name(item)
            if updated["item_name"] != item["item_name"]:
                await fetch_and_save_item_prices(updated["item_id"], updated["item_name"])
                item = updated
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
