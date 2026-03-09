import asyncio
from datetime import datetime, timedelta, timezone

import discord

from core.db import get_all_watch_items, get_price_history, get_output_channel
from core.chart import generate_overview_chart, aggregate_to_ohlc
from core.logger import logger

KST = timezone(timedelta(hours=9))


async def _collect_item_data():
    """전 감시 아이템의 24시간/48시간 데이터 수집"""
    watch_items = await get_all_watch_items()
    if not watch_items:
        return []

    now = datetime.now(KST)
    h24_start = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    h48_start = (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    h24_end = now.strftime("%Y-%m-%d %H:%M:%S")
    h24_boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    results = []
    for item in watch_items:
        item_id = item["item_id"]
        item_name = item["item_name"]

        records_24h = await get_price_history(item_id, h24_start, h24_end)
        records_48h = await get_price_history(item_id, h48_start, h24_end)

        if not records_24h or len(records_24h) < 2:
            continue

        # 전일(24~48시간 전) 거래 분리
        prev_records = [r for r in records_48h if r["sold_date"] < h24_boundary]

        prices_24h = [r["unit_price"] for r in records_24h]
        first_price = prices_24h[0]
        current_price = prices_24h[-1]
        change_pct = ((current_price - first_price) / first_price * 100) if first_price else 0

        # 거래량
        volume_24h = sum(r["count"] for r in records_24h)
        volume_prev = sum(r["count"] for r in prev_records) if prev_records else 0
        volume_change_pct = (
            ((volume_24h - volume_prev) / volume_prev * 100) if volume_prev else 0
        )

        # 고가/저가
        high_24h = max(prices_24h)
        low_24h = min(prices_24h)

        # 골든크로스/데드크로스 감지 (일봉 MA5/MA20 기준)
        signal = await _detect_cross_signal(item_id, item_name)

        results.append({
            "name": item_name,
            "item_id": item_id,
            "prices": prices_24h,
            "current": current_price,
            "change_pct": change_pct,
            "high": high_24h,
            "low": low_24h,
            "volume": volume_24h,
            "volume_prev": volume_prev,
            "volume_change_pct": volume_change_pct,
            "signal": signal,
        })

    return results


async def _detect_cross_signal(item_id: str, item_name: str) -> str | None:
    """최근 일봉 MA5/MA20 교차 감지"""
    now = datetime.now(KST)
    start = (now - timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")

    records = await get_price_history(item_id, start, end)
    if not records:
        return None

    ohlc = aggregate_to_ohlc(records, interval_minutes=1440)
    if len(ohlc) < 20:
        return None

    closes = ohlc["close"].values
    ma5 = closes[-5:].mean()
    ma20 = closes[-20:].mean()
    prev_ma5 = closes[-6:-1].mean()
    prev_ma20 = closes[-21:-1].mean()

    if prev_ma5 <= prev_ma20 and ma5 > ma20:
        return "golden_cross"
    elif prev_ma5 >= prev_ma20 and ma5 < ma20:
        return "dead_cross"
    return None


def _build_briefing_embeds(items_data: list[dict]) -> list[discord.Embed]:
    """브리핑 embed 목록 생성"""
    now = datetime.now(KST)
    embeds = []

    # --- Embed 1: 시장 종합 ---
    total_volume = sum(d["volume"] for d in items_data)
    total_prev_volume = sum(d["volume_prev"] for d in items_data)
    avg_change = sum(d["change_pct"] for d in items_data) / len(items_data)
    vol_total_change = (
        ((total_volume - total_prev_volume) / total_prev_volume * 100)
        if total_prev_volume else 0
    )

    up_count = sum(1 for d in items_data if d["change_pct"] > 0)
    down_count = sum(1 for d in items_data if d["change_pct"] < 0)
    flat_count = len(items_data) - up_count - down_count

    market_arrow = "▲" if avg_change > 0 else "▼" if avg_change < 0 else "−"
    market_color = 0xE74C3C if avg_change > 0 else 0x3498DB if avg_change < 0 else 0x95A5A6
    vol_arrow = "▲" if vol_total_change > 0 else "▼" if vol_total_change < 0 else "−"

    header = discord.Embed(
        title="경제 브리핑",
        description=f"{now.strftime('%Y년 %m월 %d일')} 06:00 기준",
        color=market_color
    )
    header.add_field(
        name="시장 평균 변동률",
        value=f"{market_arrow} {abs(avg_change):.1f}%",
        inline=True
    )
    header.add_field(
        name="총 거래량",
        value=f"{total_volume:,}개 ({vol_arrow}{abs(vol_total_change):.1f}%)",
        inline=True
    )
    header.add_field(
        name="상승/하락/보합",
        value=f"{up_count} / {down_count} / {flat_count}",
        inline=True
    )
    embeds.append(header)

    # --- Embed 2: 아이템별 시세 변동 ---
    sorted_items = sorted(items_data, key=lambda x: x["change_pct"], reverse=True)

    price_embed = discord.Embed(
        title="아이템별 시세 변동 (24시간)",
        color=0x2C3E50
    )

    for d in sorted_items:
        arrow = "▲" if d["change_pct"] > 0 else "▼" if d["change_pct"] < 0 else "−"
        color_tag = "🔴" if d["change_pct"] > 0 else "🔵" if d["change_pct"] < 0 else "⚪"
        vol_arrow = "▲" if d["volume_change_pct"] > 0 else "▼" if d["volume_change_pct"] < 0 else "−"

        value = (
            f"{color_tag} {int(d['current']):,}G "
            f"({arrow}{abs(d['change_pct']):.1f}%)\n"
            f"고가 {int(d['high']):,} / 저가 {int(d['low']):,} / "
            f"거래량 {d['volume']:,} ({vol_arrow}{abs(d['volume_change_pct']):.0f}%)"
        )
        price_embed.add_field(name=d["name"], value=value, inline=False)

    embeds.append(price_embed)

    # --- Embed 3: 추세 시그널 (있는 경우만) ---
    signals = [d for d in items_data if d["signal"]]
    if signals:
        signal_embed = discord.Embed(
            title="추세 시그널",
            description="일봉 MA5/MA20 교차 감지",
            color=0xF39C12
        )
        for d in signals:
            if d["signal"] == "golden_cross":
                signal_embed.add_field(
                    name=f"🔴 {d['name']}",
                    value="골든크로스 (MA5 > MA20) — 상승 추세 전환",
                    inline=False
                )
            else:
                signal_embed.add_field(
                    name=f"🔵 {d['name']}",
                    value="데드크로스 (MA5 < MA20) — 하락 추세 전환",
                    inline=False
                )
        embeds.append(signal_embed)

    return embeds


async def send_morning_briefing(bot, guild_id: str):
    """경제 브리핑 생성 후 채널에 발송"""
    logger.info("경제 브리핑 생성 시작")

    items_data = await _collect_item_data()
    if not items_data:
        logger.info("브리핑 대상 아이템 없음, 스킵")
        return

    embeds = _build_briefing_embeds(items_data)

    # 스파크라인 차트 생성
    chart_data = sorted(items_data, key=lambda x: abs(x["change_pct"]), reverse=True)
    chart_buf = generate_overview_chart(chart_data)

    channel_id = await get_output_channel(guild_id)
    if not channel_id:
        logger.warning("브리핑 발송 채널 없음")
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        logger.warning(f"채널 {channel_id}을 찾을 수 없음")
        return

    # embed 발송
    await channel.send(embeds=embeds)

    # 스파크라인 이미지 별도 발송
    if chart_buf:
        file = discord.File(chart_buf, filename="briefing_overview.png")
        chart_embed = discord.Embed(color=0x2C3E50)
        chart_embed.set_image(url="attachment://briefing_overview.png")
        await channel.send(embed=chart_embed, file=file)

    logger.info("경제 브리핑 발송 완료")
