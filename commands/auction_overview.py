from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands, Interaction

from core.db import get_all_watch_items, get_price_history
from core.chart import generate_overview_chart, filter_price_outliers
from core.logger import logger

KST = timezone(timedelta(hours=9))


def _calc_item_data(records: list, item_name: str) -> dict | None:
    """단일 아이템의 24시간 시세 데이터를 계산. 데이터 부족 시 None."""
    if not records or len(records) < 2:
        return None
    records = filter_price_outliers(records)
    prices = [r["unit_price"] for r in records]
    first_price = prices[0]
    current_price = prices[-1]
    change_pct = ((current_price - first_price) / first_price * 100) if first_price else 0
    return {
        "name": item_name,
        "prices": prices,
        "current": current_price,
        "change_pct": change_pct
    }


async def _collect_items_data(watch_items: list[dict], start_str: str, end_str: str) -> list[dict]:
    """모든 감시 아이템의 24시간 시세 데이터 수집."""
    items_data = []
    for item in watch_items:
        records = await get_price_history(item["item_id"], start_str, end_str)
        data = _calc_item_data(records, item["item_name"])
        if data:
            items_data.append(data)
    items_data.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return items_data


@app_commands.command(name="시세현황", description="등록된 아이템들의 24시간 시세 변동을 한눈에 보여줍니다")
async def auction_overview(interaction: Interaction):
    logger.info(f"/시세현황 호출: 사용자={interaction.user.id}")
    await interaction.response.defer(thinking=True)

    watch_items = await get_all_watch_items()
    if not watch_items:
        await interaction.followup.send("등록된 감시 아이템이 없습니다.")
        return

    end_dt = datetime.now(KST)
    start_dt = end_dt - timedelta(hours=24)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    items_data = await _collect_items_data(watch_items, start_str, end_str)
    if not items_data:
        await interaction.followup.send("최근 24시간 거래 기록이 있는 아이템이 없습니다.")
        return

    chart_buf = generate_overview_chart(items_data)
    if not chart_buf:
        await interaction.followup.send("차트 생성에 실패했습니다.")
        return

    file = discord.File(chart_buf, filename="overview.png")
    embed = discord.Embed(
        title="시세 현황 (24시간)",
        description=f"감시 아이템 {len(items_data)}개",
        color=0x2ECC71
    )
    embed.set_image(url="attachment://overview.png")

    await interaction.followup.send(embed=embed, file=file)
