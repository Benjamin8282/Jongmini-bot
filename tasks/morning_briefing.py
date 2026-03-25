import asyncio
from datetime import datetime, timedelta, timezone

import discord

from core.db import get_all_watch_items, get_price_history, get_output_channel
from core.chart import generate_overview_chart, aggregate_to_ohlc
from core.logger import logger

KST = timezone(timedelta(hours=9))


def _compute_time_ranges(now):
    """24시간/48시간 시간 범위 계산"""
    h24_start = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    h48_start = (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    h24_end = now.strftime("%Y-%m-%d %H:%M:%S")
    h24_boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    return h24_start, h48_start, h24_end, h24_boundary


def _calc_price_change_pct(prices):
    """첫 가격 대비 마지막 가격 변동률 계산"""
    first, last = prices[0], prices[-1]
    return ((last - first) / first * 100) if first else 0


def _filter_prev_records(records_48h, h24_boundary):
    return [r for r in records_48h if r["sold_date"] < h24_boundary]


def _pct_change(current, previous):
    return ((current - previous) / previous * 100) if previous else 0


def _calc_volume_stats(records_24h, records_48h, h24_boundary):
    """24시간/전일 거래량 및 변동률 계산"""
    prev_records = _filter_prev_records(records_48h, h24_boundary)
    volume_24h = sum(r["count"] for r in records_24h)
    volume_prev = sum(r["count"] for r in prev_records) if prev_records else 0
    return volume_24h, volume_prev, _pct_change(volume_24h, volume_prev)


def _build_item_result(item_name, item_id, records_24h, records_48h, h24_boundary, signal):
    """단일 아이템의 24시간 분석 결과 생성"""
    if not records_24h or len(records_24h) < 2:
        return None

    prices_24h = [r["unit_price"] for r in records_24h]
    change_pct = _calc_price_change_pct(prices_24h)
    volume_24h, volume_prev, volume_change_pct = _calc_volume_stats(
        records_24h, records_48h, h24_boundary
    )

    return {
        "name": item_name,
        "item_id": item_id,
        "prices": prices_24h,
        "current": prices_24h[-1],
        "change_pct": change_pct,
        "high": max(prices_24h),
        "low": min(prices_24h),
        "volume": volume_24h,
        "volume_prev": volume_prev,
        "volume_change_pct": volume_change_pct,
        "signal": signal,
    }


_BRIEFING_SEM = asyncio.Semaphore(5)


async def _fetch_single_item(item, h24_start, h48_start, h24_end, h24_boundary):
    """단일 아이템의 24시간/48시간 데이터 + 교차 시그널을 병렬 수집."""
    async with _BRIEFING_SEM:
        item_id = item["item_id"]
        item_name = item["item_name"]

        records_24h, records_48h, signal = await asyncio.gather(
            get_price_history(item_id, h24_start, h24_end),
            get_price_history(item_id, h48_start, h24_end),
            _detect_cross_signal(item_id, item_name),
        )

    return _build_item_result(item_name, item_id, records_24h, records_48h, h24_boundary, signal)


async def _collect_item_data():
    """전 감시 아이템의 24시간/48시간 데이터 병렬 수집"""
    watch_items = await get_all_watch_items()
    if not watch_items:
        return []

    now = datetime.now(KST)
    h24_start, h48_start, h24_end, h24_boundary = _compute_time_ranges(now)

    results = await asyncio.gather(*(
        _fetch_single_item(item, h24_start, h48_start, h24_end, h24_boundary)
        for item in watch_items
    ))
    return [r for r in results if r is not None]


def _determine_cross_type(closes):
    """MA5/MA20 교차 방향 판별"""
    ma5 = closes[-5:].mean()
    ma20 = closes[-20:].mean()
    prev_ma5 = closes[-6:-1].mean()
    prev_ma20 = closes[-21:-1].mean()

    if prev_ma5 <= prev_ma20 and ma5 > ma20:
        return "golden_cross"
    if prev_ma5 >= prev_ma20 and ma5 < ma20:
        return "dead_cross"
    return None


async def _detect_cross_signal(item_id: str, item_name: str) -> str | None:
    """최근 일봉 MA5/MA20 교차 감지"""
    now = datetime.now(KST)
    start = (now - timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")

    records = await get_price_history(item_id, start, end)
    if not records:
        return None

    ohlc = await asyncio.to_thread(aggregate_to_ohlc, records, 1440)
    if len(ohlc) < 20:
        return None

    return _determine_cross_type(ohlc["close"].values)


def _arrow_for(value):
    """값의 부호에 따른 화살표 반환"""
    if value > 0:
        return "▲"
    if value < 0:
        return "▼"
    return "−"


def _color_for_change(value):
    """변동률에 따른 embed 색상 반환"""
    if value > 0:
        return 0xE74C3C
    if value < 0:
        return 0x3498DB
    return 0x95A5A6


def _count_change_direction(items_data):
    up = sum(1 for d in items_data if d["change_pct"] > 0)
    down = sum(1 for d in items_data if d["change_pct"] < 0)
    return up, down, len(items_data) - up - down


def _calc_market_aggregates(items_data: list[dict]) -> dict:
    """시장 전체 집계 지표 계산"""
    total_volume = sum(d["volume"] for d in items_data)
    total_prev_volume = sum(d["volume_prev"] for d in items_data)
    avg_change = sum(d["change_pct"] for d in items_data) / len(items_data)
    up_count, down_count, flat_count = _count_change_direction(items_data)
    return {
        "total_volume": total_volume,
        "avg_change": avg_change,
        "vol_total_change": _pct_change(total_volume, total_prev_volume),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
    }


def _build_market_summary_embed(items_data: list[dict], now: datetime) -> discord.Embed:
    """시장 종합 embed 생성"""
    agg = _calc_market_aggregates(items_data)

    header = discord.Embed(
        title="경제 브리핑",
        description=f"{now.strftime('%Y년 %m월 %d일')} 06:00 기준",
        color=_color_for_change(agg["avg_change"])
    )
    header.add_field(
        name="시장 평균 변동률",
        value=f"{_arrow_for(agg['avg_change'])} {abs(agg['avg_change']):.1f}%",
        inline=True
    )
    header.add_field(
        name="총 거래량",
        value=(
            f"{agg['total_volume']:,}개 "
            f"({_arrow_for(agg['vol_total_change'])}{abs(agg['vol_total_change']):.1f}%)"
        ),
        inline=True
    )
    header.add_field(
        name="상승/하락/보합",
        value=f"{agg['up_count']} / {agg['down_count']} / {agg['flat_count']}",
        inline=True
    )
    return header


def _build_item_field_value(d: dict) -> str:
    """단일 아이템 필드 값 문자열 생성"""
    arrow = _arrow_for(d["change_pct"])
    color_tag = "🔴" if d["change_pct"] > 0 else "🔵" if d["change_pct"] < 0 else "⚪"
    vol_arrow = _arrow_for(d["volume_change_pct"])

    return (
        f"{color_tag} {int(d['current']):,}G "
        f"({arrow}{abs(d['change_pct']):.1f}%)\n"
        f"고가 {int(d['high']):,} / 저가 {int(d['low']):,} / "
        f"거래량 {d['volume']:,} ({vol_arrow}{abs(d['volume_change_pct']):.0f}%)"
    )


def _build_price_change_embed(items_data: list[dict]) -> discord.Embed:
    """아이템별 시세 변동 embed 생성"""
    sorted_items = sorted(items_data, key=lambda x: x["change_pct"], reverse=True)

    price_embed = discord.Embed(
        title="아이템별 시세 변동 (24시간)",
        color=0x2C3E50
    )

    for d in sorted_items:
        price_embed.add_field(name=d["name"], value=_build_item_field_value(d), inline=False)

    return price_embed


def _build_signal_embed(items_data: list[dict]) -> discord.Embed | None:
    """추세 시그널 embed 생성 (시그널이 있는 경우만)"""
    signals = [d for d in items_data if d["signal"]]
    if not signals:
        return None

    signal_embed = discord.Embed(
        title="추세 시그널",
        description="일봉 MA5/MA20 교차 감지",
        color=0xF39C12
    )
    _SIGNAL_MAP = {
        "golden_cross": ("🔴", "골든크로스 (MA5 > MA20) — 상승 추세 전환"),
        "dead_cross": ("🔵", "데드크로스 (MA5 < MA20) — 하락 추세 전환"),
    }
    for d in signals:
        icon, desc = _SIGNAL_MAP.get(d["signal"], ("⚪", "알 수 없는 시그널"))
        signal_embed.add_field(
            name=f"{icon} {d['name']}",
            value=desc,
            inline=False
        )
    return signal_embed


def _build_briefing_embeds(items_data: list[dict]) -> list[discord.Embed]:
    """브리핑 embed 목록 생성"""
    now = datetime.now(KST)
    embeds = [
        _build_market_summary_embed(items_data, now),
        _build_price_change_embed(items_data),
    ]

    signal_embed = _build_signal_embed(items_data)
    if signal_embed:
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
    chart_buf = await asyncio.to_thread(generate_overview_chart, chart_data)

    channel_id = await get_output_channel(guild_id, 'economy')
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
