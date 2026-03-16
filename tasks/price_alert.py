from datetime import datetime, timedelta, timezone

import discord

from core.db import (
    get_price_history, get_output_channel,
    get_all_user_alerts_for_item, disable_user_alert,
)
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


def _try_emit(item_id: str, event_type: str, data: dict,
              clear_types: list[str] | None = None) -> dict | None:
    """쿨다운 체크 후 알림 데이터 반환. 쿨다운 중이면 None."""
    if _is_on_cooldown(item_id, event_type):
        return None
    _set_cooldown(item_id, event_type)
    for ct in (clear_types or []):
        _clear_cooldown(item_id, ct)
    return data


# ─── check_price_alerts 헬퍼 ───


def _calc_price_bounds(past_prices: list[int]) -> tuple[float, int]:
    """IQR 기반 이상치 상한선 및 중앙값 계산."""
    sorted_prices = sorted(past_prices)
    n = len(sorted_prices)
    median_price = sorted_prices[n // 2]
    q1 = sorted_prices[n // 4]
    q3 = sorted_prices[3 * n // 4]
    iqr = q3 - q1

    if iqr > 0:
        upper_bound = q3 + 3 * iqr
        if median_price > 0:
            upper_bound = max(upper_bound, median_price * 3.0)
    elif median_price > 0:
        upper_bound = median_price * 5.0
    else:
        upper_bound = float("inf")

    return upper_bound, median_price


def _detect_surge_crash(item_id: str, item_name: str,
                        h1_records: list[dict]) -> list[dict]:
    """1시간 급등/급락 감지."""
    if not h1_records or len(h1_records) < 2:
        return []

    first_price = h1_records[0]["unit_price"]
    last_price = h1_records[-1]["unit_price"]
    if first_price <= 0:
        return []

    change_pct = (last_price - first_price) / first_price * 100
    alerts = []

    if change_pct >= 30:
        alert = _try_emit(item_id, "surge", {
            "level": "urgent", "type": "surge",
            "item_name": item_name, "change_pct": change_pct,
            "price": last_price,
        }, clear_types=["crash"])
        if alert:
            alerts.append(alert)
    elif change_pct <= -30:
        alert = _try_emit(item_id, "crash", {
            "level": "urgent", "type": "crash",
            "item_name": item_name, "change_pct": change_pct,
            "price": last_price,
        }, clear_types=["surge"])
        if alert:
            alerts.append(alert)

    return alerts


def _detect_price_anomalies(
    item_id: str, item_name: str,
    current_price: int, past_prices: list[int],
    upper_bound: float, median_price: int
) -> list[dict]:
    """비정상 고가/저가 및 신고가/신저가 감지."""
    alerts = []
    fat_finger_high = False
    fat_finger_low = False

    # 비정상 고가 (0 추가 실수 등)
    if median_price > 0 and current_price > upper_bound:
        fat_finger_high = True
        overprice = (current_price / median_price - 1) * 100
        alert = _try_emit(item_id, "fat_finger_high", {
            "level": "fun", "type": "fat_finger_high",
            "item_name": item_name, "price": current_price,
            "median_price": median_price, "overprice": overprice,
        })
        if alert:
            alerts.append(alert)

    # 신고가 (이상치가 아닌 경우만)
    if not fat_finger_high:
        clean_past = [p for p in past_prices if p <= upper_bound] or past_prices
        past_high = max(clean_past)
        if current_price > past_high:
            alert = _try_emit(item_id, "new_high", {
                "level": "major", "type": "new_high",
                "item_name": item_name, "price": current_price,
                "prev_high": past_high,
            })
            if alert:
                alerts.append(alert)

    # 0빼기 파격세일
    if median_price > 0 and current_price < median_price * 0.6:
        fat_finger_low = True
        discount = (1 - current_price / median_price) * 100
        alert = _try_emit(item_id, "fat_finger", {
            "level": "fun", "type": "fat_finger",
            "item_name": item_name, "price": current_price,
            "median_price": median_price, "discount": discount,
        })
        if alert:
            alerts.append(alert)

    # 신저가 (파격세일이 아닌 경우만)
    if not fat_finger_low:
        past_low = min(past_prices)
        if current_price < past_low:
            alert = _try_emit(item_id, "new_low", {
                "level": "major", "type": "new_low",
                "item_name": item_name, "price": current_price,
                "prev_low": past_low,
            })
            if alert:
                alerts.append(alert)

    return alerts


async def _detect_volume_spike(
    item_id: str, item_name: str,
    h1_records: list[dict], now: datetime, now_str: str
) -> list[dict]:
    """거래량 폭증 감지."""
    if not h1_records:
        return []

    d1_start = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    d1_records = await get_price_history(item_id, d1_start, now_str)
    if not d1_records:
        return []

    vol_1h = sum(r["count"] for r in h1_records)
    vol_24h = sum(r["count"] for r in d1_records)
    avg_hourly = vol_24h / 24

    if avg_hourly <= 0 or vol_1h < avg_hourly * 10:
        return []

    alert = _try_emit(item_id, "volume_spike", {
        "level": "major", "type": "volume_spike",
        "item_name": item_name, "vol_1h": vol_1h,
        "avg_hourly": avg_hourly,
    })
    return [alert] if alert else []


def _detect_rsi_signal(item_id: str, item_name: str,
                       closes) -> list[dict]:
    """RSI 과매수/과매도 시그널 감지."""
    rsi = calc_rsi(closes)
    if rsi is None:
        return []

    prev = _prev_state.get(item_id, {})
    prev_zone = prev.get("rsi_zone", "neutral")

    if rsi > 70:
        curr_zone = "overbought"
    elif rsi < 30:
        curr_zone = "oversold"
    else:
        curr_zone = "neutral"

    _prev_state.setdefault(item_id, {})["rsi_zone"] = curr_zone
    alerts = []

    if curr_zone != prev_zone and curr_zone != "neutral":
        event = "rsi_overbought" if curr_zone == "overbought" else "rsi_oversold"
        alert = _try_emit(item_id, event, {
            "level": "info", "type": event,
            "item_name": item_name, "rsi": rsi,
        })
        if alert:
            alerts.append(alert)

    return alerts


def _detect_ma_cross(item_id: str, item_name: str,
                     closes) -> list[dict]:
    """골든/데드 크로스 감지."""
    if len(closes) < 20:
        return []

    ma_info = calc_ma_alignment(closes)
    ma5, ma20 = ma_info["ma5"], ma_info["ma20"]
    if ma5 is None or ma20 is None:
        return []

    currently_above = ma5 > ma20
    prev = _prev_state.get(item_id, {})
    was_above = prev.get("ma5_above_ma20")
    _prev_state.setdefault(item_id, {})["ma5_above_ma20"] = currently_above

    if was_above is None or currently_above == was_above:
        return []

    event_type = "golden_cross" if currently_above else "dead_cross"
    alert = _try_emit(item_id, event_type, {
        "level": "info", "type": event_type, "item_name": item_name,
    })
    return [alert] if alert else []


async def check_price_alerts(item_id: str, item_name: str) -> list[dict]:
    """아이템의 시세 데이터를 분석하여 알림 이벤트 목록 반환."""
    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 1시간 데이터: 급등/급락
    h1_start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    h1_records = await get_price_history(item_id, h1_start, now_str)
    alerts = _detect_surge_crash(item_id, item_name, h1_records)

    # 14일 데이터: 가격 이벤트 + 기술적 시그널
    d14_start = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    d14_records = await get_price_history(item_id, d14_start, now_str)

    if not d14_records or len(d14_records) < 10:
        return alerts

    all_prices = [r["unit_price"] for r in d14_records]
    current_price = all_prices[-1]
    past_prices = all_prices[:-1]

    upper_bound, median_price = _calc_price_bounds(past_prices)
    alerts.extend(_detect_price_anomalies(
        item_id, item_name, current_price, past_prices,
        upper_bound, median_price
    ))

    # 거래량 폭증
    alerts.extend(await _detect_volume_spike(
        item_id, item_name, h1_records, now, now_str
    ))

    # 기술적 시그널 (일봉 기준)
    ohlc = aggregate_to_ohlc(d14_records, interval_minutes=1440)
    if len(ohlc) >= 5:
        closes = ohlc["close"]
        alerts.extend(_detect_rsi_signal(item_id, item_name, closes))
        alerts.extend(_detect_ma_cross(item_id, item_name, closes))

    return alerts


# ─── build_alert_embed 헬퍼 ───


def _embed_surge(a):
    return discord.Embed(
        title=f"[긴급] {a['item_name']} 급등!",
        description=(
            f"**1시간 내 +{a['change_pct']:.1f}% 상승**\n"
            f"현재가 {int(a['price']):,}G\n\n"
            f"평소보다 빠른 상승세입니다.\n"
            f"단기 과열일 수 있으니 추이를 지켜보세요."
        ),
        color=0xFF4757
    )


def _embed_crash(a):
    return discord.Embed(
        title=f"[긴급] {a['item_name']} 급락!",
        description=(
            f"**1시간 내 {a['change_pct']:.1f}% 하락**\n"
            f"현재가 {int(a['price']):,}G\n\n"
            f"급격한 가격 하락이 발생했습니다.\n"
            f"패닉 매도일 수 있으니 신중하게 판단하세요."
        ),
        color=0x3498FF
    )


def _embed_new_high(a):
    return discord.Embed(
        title=f"[주요] {a['item_name']} 14일 신고가 갱신!",
        description=(
            f"현재가 **{int(a['price']):,}G**\n"
            f"이전 최고가 {int(a['prev_high']):,}G\n\n"
            f"14일 동안의 최고 가격을 돌파했습니다.\n"
            f"상승 추세가 이어질 수 있지만, 저항선 근처에서는 주의하세요."
        ),
        color=0xFF6348
    )


def _embed_new_low(a):
    return discord.Embed(
        title=f"[주요] {a['item_name']} 14일 신저가 갱신!",
        description=(
            f"현재가 **{int(a['price']):,}G**\n"
            f"이전 최저가 {int(a['prev_low']):,}G\n\n"
            f"14일 동안의 최저 가격을 갱신했습니다.\n"
            f"추가 하락 가능성이 있지만, 반등 구간이 될 수도 있습니다."
        ),
        color=0x3498FF
    )


def _embed_volume_spike(a):
    ratio = a["vol_1h"] / a["avg_hourly"] if a["avg_hourly"] else 0
    return discord.Embed(
        title=f"[주요] {a['item_name']} 거래 폭증!",
        description=(
            f"최근 1시간 거래량: **{int(a['vol_1h']):,}개**\n"
            f"24시간 평균: {int(a['avg_hourly']):,}개/시간"
            f" (약 {ratio:.1f}배)\n\n"
            f"거래가 평소보다 훨씬 활발합니다.\n"
            f"큰 가격 움직임이 올 수 있으니 주목하세요."
        ),
        color=0xFFA502
    )


def _embed_golden_cross(a):
    return discord.Embed(
        title=f"[참고] {a['item_name']} 골든크로스 발생",
        description=(
            "단기 평균(MA5)이 장기 평균(MA20)을 **위로 돌파**했습니다.\n\n"
            "하락하던 가격이 상승으로 전환될 수 있는 신호입니다.\n"
            "다만 거래량이 뒷받침되는지 함께 확인하세요."
        ),
        color=0xFF6348
    )


def _embed_dead_cross(a):
    return discord.Embed(
        title=f"[참고] {a['item_name']} 데드크로스 발생",
        description=(
            "단기 평균(MA5)이 장기 평균(MA20)을 **아래로 돌파**했습니다.\n\n"
            "상승하던 가격이 하락으로 전환될 수 있는 신호입니다.\n"
            "매수를 고려 중이라면 조금 더 지켜보는 것이 안전합니다."
        ),
        color=0x3498FF
    )


def _embed_rsi_overbought(a):
    return discord.Embed(
        title=f"[참고] {a['item_name']} 과매수 구간 진입",
        description=(
            f"RSI(14)가 **{a['rsi']:.1f}**로 70을 넘었습니다.\n\n"
            "최근 사려는 힘이 과하게 쏠렸다는 뜻입니다.\n"
            "가격이 곧 조정(하락)을 받을 수 있으니\n"
            "지금 매수는 신중하게 판단하세요."
        ),
        color=0xFFA502
    )


def _embed_rsi_oversold(a):
    return discord.Embed(
        title=f"[참고] {a['item_name']} 과매도 구간 진입",
        description=(
            f"RSI(14)가 **{a['rsi']:.1f}**로 30 아래로 내려갔습니다.\n\n"
            "최근 팔려는 힘이 과하게 쏠렸다는 뜻입니다.\n"
            "가격이 충분히 떨어져서 반등할 가능성이 있습니다.\n"
            "바닥 매수를 고려해볼 수 있는 구간입니다."
        ),
        color=0x2ED573
    )


def _embed_fat_finger_high(a):
    return discord.Embed(
        title=f"[비정상 고가] {a['item_name']} +{a['overprice']:.0f}%",
        description=(
            f"**{int(a['price']):,}G**에 거래가 잡혔습니다\n"
            f"시세 중앙값 {int(a['median_price']):,}G\n\n"
            f"0을 더 붙인 실수이거나 비정상 거래로 보입니다.\n"
            f"이 가격은 시세 분석에서 자동 제외됩니다."
        ),
        color=0xFF6348
    )


def _embed_fat_finger(a):
    return discord.Embed(
        title=f"\U0001f6a8 [파격세일] {a['item_name']} {a['discount']:.0f}% OFF!!",
        description=(
            f"누군가 **{int(a['price']):,}G**에 올렸습니다\n"
            f"시세 중앙값 {int(a['median_price']):,}G\n\n"
            f"0 빼먹은 거 아닌지 의심됩니다...\n"
            f"눈치 빠른 모험가에게는 로또일 수도?"
        ),
        color=0xFEE75C
    )


def _embed_price_above(a):
    return discord.Embed(
        title=f"[지정가] {a['item_name']} 목표가 돌파!",
        description=(
            f"현재가 **{int(a['price']):,}G**\n"
            f"설정가 {int(a['target']):,}G 이상 도달\n\n"
            f"이 알림은 자동으로 해제됩니다."
        ),
        color=0xFF6348
    )


def _embed_price_below(a):
    return discord.Embed(
        title=f"[지정가] {a['item_name']} 지지선 이탈!",
        description=(
            f"현재가 **{int(a['price']):,}G**\n"
            f"설정가 {int(a['target']):,}G 이하로 하락\n\n"
            f"이 알림은 자동으로 해제됩니다."
        ),
        color=0x3498FF
    )


_EMBED_BUILDERS = {
    "surge": _embed_surge,
    "crash": _embed_crash,
    "new_high": _embed_new_high,
    "new_low": _embed_new_low,
    "volume_spike": _embed_volume_spike,
    "golden_cross": _embed_golden_cross,
    "dead_cross": _embed_dead_cross,
    "rsi_overbought": _embed_rsi_overbought,
    "rsi_oversold": _embed_rsi_oversold,
    "fat_finger_high": _embed_fat_finger_high,
    "fat_finger": _embed_fat_finger,
    "price_above": _embed_price_above,
    "price_below": _embed_price_below,
}


def build_alert_embed(alert: dict) -> discord.Embed:
    """알림 이벤트를 Discord embed로 변환."""
    builder = _EMBED_BUILDERS.get(alert["type"])
    if builder:
        embed = builder(alert)
    else:
        embed = discord.Embed(
            title=f"{alert['item_name']} 시세 알림",
            description=str(alert),
            color=0x95A5A6
        )
    embed.timestamp = datetime.now(KST)
    return embed


# ─── 채널 알림 발송 ───


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
                reg_time = datetime.strptime(
                    registered_at, "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=KST)
            if datetime.now(KST) - reg_time < timedelta(hours=ALERT_WARMUP_HOURS):
                return

        alerts = await check_price_alerts(item_id, item_name)
        if not alerts:
            return

        channel_id = await get_output_channel(guild_id, 'economy')
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


# ─── 사용자별 DM 알림 ───


# 사용자별 쿨다운: {(user_id, item_id, event_type): datetime}
_user_cooldowns: dict[tuple[int, str, str], datetime] = {}
USER_COOLDOWN_MINUTES = 60


def _is_user_on_cooldown(user_id: int, item_id: str,
                         event_type: str) -> bool:
    key = (user_id, item_id, event_type)
    last = _user_cooldowns.get(key)
    if last is None:
        return False
    return datetime.now(KST) - last < timedelta(minutes=USER_COOLDOWN_MINUTES)


def _set_user_cooldown(user_id: int, item_id: str, event_type: str):
    _user_cooldowns[(user_id, item_id, event_type)] = datetime.now(KST)


async def _collect_market_snapshot(item_id: str) -> dict:
    """알림 평가에 필요한 시장 데이터를 1회 수집."""
    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    h1_start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    d14_start = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    d1_start = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    h1_records = await get_price_history(item_id, h1_start, now_str)
    d14_records = await get_price_history(item_id, d14_start, now_str)
    d1_records = await get_price_history(item_id, d1_start, now_str)

    # 현재가
    current_price = d14_records[-1]["unit_price"] if d14_records else None

    # 1시간 변동률
    change_pct = None
    if h1_records and len(h1_records) >= 2:
        first = h1_records[0]["unit_price"]
        last = h1_records[-1]["unit_price"]
        if first > 0:
            change_pct = (last - first) / first * 100

    # 거래량
    vol_1h = sum(r["count"] for r in h1_records) if h1_records else 0
    vol_24h = sum(r["count"] for r in d1_records) if d1_records else 0

    # RSI
    rsi = None
    if d14_records and len(d14_records) >= 10:
        ohlc = aggregate_to_ohlc(d14_records, interval_minutes=1440)
        if len(ohlc) >= 5:
            rsi = calc_rsi(ohlc["close"])

    return {
        "now": now,
        "current_price": current_price,
        "change_pct": change_pct,
        "vol_1h": vol_1h,
        "avg_hourly": vol_24h / 24 if vol_24h > 0 else 0,
        "rsi": rsi,
        "d14_records": d14_records or [],
    }


def _check_ua_surge(tv, snap):
    pct = snap["change_pct"]
    if pct is not None and pct >= tv:
        return {"change_pct": pct, "price": snap["current_price"]}
    return None


def _check_ua_crash(tv, snap):
    pct = snap["change_pct"]
    if pct is not None and pct <= -tv:
        return {"change_pct": pct, "price": snap["current_price"]}
    return None


def _check_ua_price_window(tv, snap, direction: str):
    """new_high / new_low 공통: 기간 내 가격 윈도우 비교."""
    cp = snap["current_price"]
    if not cp or not snap["d14_records"]:
        return None
    cutoff = (snap["now"] - timedelta(days=int(tv))).strftime("%Y-%m-%d %H:%M:%S")
    window = [r["unit_price"] for r in snap["d14_records"]
              if r["sold_date"] >= cutoff]
    if len(window) <= 1:
        return None
    past = window[:-1]
    if direction == "high" and cp > max(past):
        return {"price": cp, "prev_high": max(past)}
    if direction == "low" and cp < min(past):
        return {"price": cp, "prev_low": min(past)}
    return None


def _check_ua_volume(tv, snap):
    if snap["avg_hourly"] > 0 and snap["vol_1h"] >= snap["avg_hourly"] * tv:
        return {"vol_1h": snap["vol_1h"], "avg_hourly": snap["avg_hourly"]}
    return None


def _check_ua_rsi(tv, snap, direction: str):
    rsi = snap["rsi"]
    if rsi is None:
        return None
    if direction == "upper" and rsi > tv:
        return {"rsi": rsi, "_override_type": "rsi_overbought"}
    if direction == "lower" and rsi < tv:
        return {"rsi": rsi, "_override_type": "rsi_oversold"}
    return None


def _check_ua_price_target(tv, snap, direction: str):
    cp = snap["current_price"]
    if cp is None:
        return None
    if direction == "above" and cp >= tv:
        return {"price": cp, "target": tv}
    if direction == "below" and cp <= tv:
        return {"price": cp, "target": tv}
    return None


_USER_ALERT_CHECKERS = {
    "surge": lambda tv, s: _check_ua_surge(tv, s),
    "crash": lambda tv, s: _check_ua_crash(tv, s),
    "new_high": lambda tv, s: _check_ua_price_window(tv, s, "high"),
    "new_low": lambda tv, s: _check_ua_price_window(tv, s, "low"),
    "volume_spike": lambda tv, s: _check_ua_volume(tv, s),
    "rsi_upper": lambda tv, s: _check_ua_rsi(tv, s, "upper"),
    "rsi_lower": lambda tv, s: _check_ua_rsi(tv, s, "lower"),
    "price_above": lambda tv, s: _check_ua_price_target(tv, s, "above"),
    "price_below": lambda tv, s: _check_ua_price_target(tv, s, "below"),
}


def _evaluate_user_alert(ua: dict, snap: dict) -> dict | None:
    """단일 사용자 알림 조건을 평가하여 트리거되면 데이터 반환."""
    checker = _USER_ALERT_CHECKERS.get(ua["alert_type"])
    if checker is None:
        return None
    return checker(ua["threshold_value"], snap)


async def _send_dm_alerts(bot, user_id: int, dm_alerts: list[dict],
                          item_name: str):
    """사용자에게 DM 알림 발송."""
    try:
        user = await bot.fetch_user(user_id)
        for alert in dm_alerts:
            embed = build_alert_embed(alert)
            embed.set_footer(text="개인 알림 설정 | /시세알림으로 변경")
            await user.send(embed=embed)
            logger.info(
                f"DM 알림 발송: user={user_id}, "
                f"{item_name} - {alert['type']}"
            )
    except discord.Forbidden:
        logger.warning(f"DM 발송 실패 (DM 비활성): user={user_id}")
    except Exception as e:
        logger.error(f"DM 알림 발송 오류: user={user_id}, {e}")


async def process_user_alerts_for_item(
    bot, item_id: str, item_name: str
):
    """사용자별 커스텀 알림 체크 및 DM 발송"""
    try:
        user_alerts = await get_all_user_alerts_for_item(item_id)
        if not user_alerts:
            return

        snap = await _collect_market_snapshot(item_id)

        # 사용자별로 그룹핑
        user_groups: dict[int, list[dict]] = {}
        for ua in user_alerts:
            user_groups.setdefault(ua["user_id"], []).append(ua)

        for user_id, alerts in user_groups.items():
            dm_alerts = []

            for ua in alerts:
                at = ua["alert_type"]
                if _is_user_on_cooldown(user_id, item_id, at):
                    continue

                result = _evaluate_user_alert(ua, snap)
                if not result:
                    continue

                # alert_data 조립
                alert_type = result.pop("_override_type", at)
                alert_data = {"type": alert_type, "item_name": item_name}
                alert_data.update(result)

                dm_alerts.append(alert_data)
                _set_user_cooldown(user_id, item_id, at)

                # 1회성 알림이면 자동 해제
                if ua.get("one_time", 0):
                    await disable_user_alert(user_id, item_id, at)

            if dm_alerts:
                await _send_dm_alerts(bot, user_id, dm_alerts, item_name)

    except Exception as e:
        logger.error(f"사용자별 알림 처리 오류 ({item_name}): {e}")
