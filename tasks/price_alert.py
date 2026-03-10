import asyncio
from datetime import datetime, timedelta, timezone

import discord

from core.db import get_price_history, get_output_channel
from core.chart import aggregate_to_ohlc
from core.analysis import calc_rsi, calc_ma_alignment
from core.logger import logger

KST = timezone(timedelta(hours=9))

# 쿨다운 저장: {(item_id, event_type): datetime}
_cooldowns: dict[tuple[str, str], datetime] = {}
COOLDOWN_MINUTES = 60

# 이전 상태 저장: {item_id: {"rsi_zone": str, "ma5_above_ma20": bool}}
_prev_state: dict[str, dict] = {}


def _is_on_cooldown(item_id: str, event_type: str) -> bool:
    key = (item_id, event_type)
    last = _cooldowns.get(key)
    if last is None:
        return False
    return datetime.now(KST) - last < timedelta(minutes=COOLDOWN_MINUTES)


def _set_cooldown(item_id: str, event_type: str):
    _cooldowns[(item_id, event_type)] = datetime.now(KST)


def _clear_cooldown(item_id: str, event_type: str):
    _cooldowns.pop((item_id, event_type), None)


async def check_price_alerts(item_id: str, item_name: str) -> list[dict]:
    """아이템의 시세 데이터를 분석하여 알림 이벤트 목록 반환."""
    alerts = []
    now = datetime.now(KST)

    # --- 1시간 데이터: 급등/급락 감지 ---
    h1_start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    h1_records = await get_price_history(item_id, h1_start, now_str)

    if h1_records and len(h1_records) >= 2:
        first_price = h1_records[0]["unit_price"]
        last_price = h1_records[-1]["unit_price"]
        if first_price > 0:
            change_pct = (last_price - first_price) / first_price * 100

            if change_pct >= 30 and not _is_on_cooldown(item_id, "surge"):
                alerts.append({
                    "level": "urgent",
                    "type": "surge",
                    "item_name": item_name,
                    "change_pct": change_pct,
                    "price": last_price,
                })
                _set_cooldown(item_id, "surge")
                _clear_cooldown(item_id, "crash")

            elif change_pct <= -30 and not _is_on_cooldown(item_id, "crash"):
                alerts.append({
                    "level": "urgent",
                    "type": "crash",
                    "item_name": item_name,
                    "change_pct": change_pct,
                    "price": last_price,
                })
                _set_cooldown(item_id, "crash")
                _clear_cooldown(item_id, "surge")

    # --- 7일 데이터: 신고가/신저가, 거래량 폭증, 기술적 시그널 ---
    d14_start = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    d7_records = await get_price_history(item_id, d14_start, now_str)

    if not d7_records or len(d7_records) < 10:
        return alerts

    all_prices = [r["unit_price"] for r in d7_records]
    current_price = all_prices[-1]
    past_prices = all_prices[:-1]

    # 신고가
    past_high = max(past_prices)
    if current_price > past_high and not _is_on_cooldown(item_id, "new_high"):
        alerts.append({
            "level": "major",
            "type": "new_high",
            "item_name": item_name,
            "price": current_price,
            "prev_high": past_high,
        })
        _set_cooldown(item_id, "new_high")

    # 신저가
    past_low = min(past_prices)
    if current_price < past_low and not _is_on_cooldown(item_id, "new_low"):
        alerts.append({
            "level": "major",
            "type": "new_low",
            "item_name": item_name,
            "price": current_price,
            "prev_low": past_low,
        })
        _set_cooldown(item_id, "new_low")

    # 거래량 폭증: 최근 1시간 vs 24시간 평균
    d1_start = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    d1_records = await get_price_history(item_id, d1_start, now_str)

    if d1_records and h1_records:
        vol_1h = sum(r["count"] for r in h1_records)
        vol_24h = sum(r["count"] for r in d1_records)
        avg_hourly = vol_24h / 24
        if avg_hourly > 0 and vol_1h >= avg_hourly * 10:
            if not _is_on_cooldown(item_id, "volume_spike"):
                alerts.append({
                    "level": "major",
                    "type": "volume_spike",
                    "item_name": item_name,
                    "vol_1h": vol_1h,
                    "avg_hourly": avg_hourly,
                })
                _set_cooldown(item_id, "volume_spike")

    # 기술적 시그널: 일봉 기준 MA 크로스, RSI
    ohlc = aggregate_to_ohlc(d7_records, interval_minutes=1440)
    if len(ohlc) < 5:
        return alerts

    closes = ohlc["close"]
    prev = _prev_state.get(item_id, {})

    # RSI
    rsi = calc_rsi(closes)
    if rsi is not None:
        prev_zone = prev.get("rsi_zone", "neutral")
        if rsi > 70:
            curr_zone = "overbought"
        elif rsi < 30:
            curr_zone = "oversold"
        else:
            curr_zone = "neutral"

        if curr_zone == "overbought" and prev_zone != "overbought":
            if not _is_on_cooldown(item_id, "rsi_overbought"):
                alerts.append({
                    "level": "info",
                    "type": "rsi_overbought",
                    "item_name": item_name,
                    "rsi": rsi,
                })
                _set_cooldown(item_id, "rsi_overbought")

        elif curr_zone == "oversold" and prev_zone != "oversold":
            if not _is_on_cooldown(item_id, "rsi_oversold"):
                alerts.append({
                    "level": "info",
                    "type": "rsi_oversold",
                    "item_name": item_name,
                    "rsi": rsi,
                })
                _set_cooldown(item_id, "rsi_oversold")

        _prev_state.setdefault(item_id, {})["rsi_zone"] = curr_zone

    # 골든/데드 크로스
    if len(closes) >= 20:
        ma_info = calc_ma_alignment(closes)
        ma5 = ma_info["ma5"]
        ma20 = ma_info["ma20"]
        if ma5 is not None and ma20 is not None:
            currently_above = ma5 > ma20
            was_above = prev.get("ma5_above_ma20")

            if was_above is not None and currently_above != was_above:
                if currently_above:
                    event_type = "golden_cross"
                else:
                    event_type = "dead_cross"

                if not _is_on_cooldown(item_id, event_type):
                    alerts.append({
                        "level": "info",
                        "type": event_type,
                        "item_name": item_name,
                    })
                    _set_cooldown(item_id, event_type)

            _prev_state.setdefault(item_id, {})["ma5_above_ma20"] = currently_above

    return alerts


def build_alert_embed(alert: dict) -> discord.Embed:
    """알림 이벤트를 Discord embed로 변환."""
    t = alert["type"]
    name = alert["item_name"]

    if t == "surge":
        pct = alert["change_pct"]
        price = alert["price"]
        embed = discord.Embed(
            title=f"[긴급] {name} 급등!",
            description=(
                f"**1시간 내 +{pct:.1f}% 상승**\n"
                f"현재가 {int(price):,}G\n\n"
                f"평소보다 빠른 상승세입니다.\n"
                f"단기 과열일 수 있으니 추이를 지켜보세요."
            ),
            color=0xFF4757
        )

    elif t == "crash":
        pct = alert["change_pct"]
        price = alert["price"]
        embed = discord.Embed(
            title=f"[긴급] {name} 급락!",
            description=(
                f"**1시간 내 {pct:.1f}% 하락**\n"
                f"현재가 {int(price):,}G\n\n"
                f"급격한 가격 하락이 발생했습니다.\n"
                f"패닉 매도일 수 있으니 신중하게 판단하세요."
            ),
            color=0x3498FF
        )

    elif t == "new_high":
        price = alert["price"]
        prev = alert["prev_high"]
        embed = discord.Embed(
            title=f"[주요] {name} 14일 신고가 갱신!",
            description=(
                f"현재가 **{int(price):,}G**\n"
                f"이전 최고가 {int(prev):,}G\n\n"
                f"14일 동안의 최고 가격을 돌파했습니다.\n"
                f"상승 추세가 이어질 수 있지만, 저항선 근처에서는 주의하세요."
            ),
            color=0xFF6348
        )

    elif t == "new_low":
        price = alert["price"]
        prev = alert["prev_low"]
        embed = discord.Embed(
            title=f"[주요] {name} 14일 신저가 갱신!",
            description=(
                f"현재가 **{int(price):,}G**\n"
                f"이전 최저가 {int(prev):,}G\n\n"
                f"14일 동안의 최저 가격을 갱신했습니다.\n"
                f"추가 하락 가능성이 있지만, 반등 구간이 될 수도 있습니다."
            ),
            color=0x3498FF
        )

    elif t == "volume_spike":
        vol = alert["vol_1h"]
        avg = alert["avg_hourly"]
        ratio = vol / avg if avg else 0
        embed = discord.Embed(
            title=f"[주요] {name} 거래 폭증!",
            description=(
                f"최근 1시간 거래량: **{int(vol):,}개**\n"
                f"24시간 평균: {int(avg):,}개/시간 (약 {ratio:.1f}배)\n\n"
                f"거래가 평소보다 훨씬 활발합니다.\n"
                f"큰 가격 움직임이 올 수 있으니 주목하세요."
            ),
            color=0xFFA502
        )

    elif t == "golden_cross":
        embed = discord.Embed(
            title=f"[참고] {name} 골든크로스 발생",
            description=(
                "단기 평균(MA5)이 장기 평균(MA20)을 **위로 돌파**했습니다.\n\n"
                "하락하던 가격이 상승으로 전환될 수 있는 신호입니다.\n"
                "다만 거래량이 뒷받침되는지 함께 확인하세요."
            ),
            color=0xFF6348
        )

    elif t == "dead_cross":
        embed = discord.Embed(
            title=f"[참고] {name} 데드크로스 발생",
            description=(
                "단기 평균(MA5)이 장기 평균(MA20)을 **아래로 돌파**했습니다.\n\n"
                "상승하던 가격이 하락으로 전환될 수 있는 신호입니다.\n"
                "매수를 고려 중이라면 조금 더 지켜보는 것이 안전합니다."
            ),
            color=0x3498FF
        )

    elif t == "rsi_overbought":
        rsi = alert["rsi"]
        embed = discord.Embed(
            title=f"[참고] {name} 과매수 구간 진입",
            description=(
                f"RSI(14)가 **{rsi:.1f}**로 70을 넘었습니다.\n\n"
                "최근 사려는 힘이 과하게 쏠렸다는 뜻입니다.\n"
                "가격이 곧 조정(하락)을 받을 수 있으니\n"
                "지금 매수는 신중하게 판단하세요."
            ),
            color=0xFFA502
        )

    elif t == "rsi_oversold":
        rsi = alert["rsi"]
        embed = discord.Embed(
            title=f"[참고] {name} 과매도 구간 진입",
            description=(
                f"RSI(14)가 **{rsi:.1f}**로 30 아래로 내려갔습니다.\n\n"
                "최근 팔려는 힘이 과하게 쏠렸다는 뜻입니다.\n"
                "가격이 충분히 떨어져서 반등할 가능성이 있습니다.\n"
                "바닥 매수를 고려해볼 수 있는 구간입니다."
            ),
            color=0x2ED573
        )

    else:
        embed = discord.Embed(
            title=f"{name} 시세 알림",
            description=str(alert),
            color=0x95A5A6
        )

    embed.timestamp = datetime.now(KST)
    return embed


ALERT_WARMUP_HOURS = 2  # 등록 후 데이터 수집 대기 시간


async def process_alerts_for_item(
    bot, guild_id: str, item_id: str, item_name: str,
    registered_at: str = None
):
    """아이템 알림 체크 후 채널에 발송. 등록 직후에는 스킵."""
    try:
        # 등록 후 충분한 데이터가 쌓일 때까지 알림 스킵
        if registered_at:
            try:
                reg_time = datetime.fromisoformat(registered_at).replace(tzinfo=KST)
            except ValueError:
                reg_time = datetime.strptime(registered_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            if datetime.now(KST) - reg_time < timedelta(hours=ALERT_WARMUP_HOURS):
                return

        alerts = await check_price_alerts(item_id, item_name)
        if not alerts:
            return

        channel_id = await get_output_channel(guild_id)
        if not channel_id:
            return

        channel = bot.get_channel(int(channel_id))
        if not channel:
            return

        for alert in alerts:
            embed = build_alert_embed(alert)
            await channel.send(embed=embed)
            logger.info(
                f"시세 알림 발송: {item_name} - {alert['type']} ({alert['level']})"
            )

    except Exception as e:
        logger.error(f"시세 알림 처리 오류 ({item_name}): {e}")
