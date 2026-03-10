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

    # 0빼기 파격세일 감지: 중앙값의 60% 이하면 실수 거래로 판단
    sorted_prices = sorted(past_prices)
    median_price = sorted_prices[len(sorted_prices) // 2]
    fat_finger = False
    if median_price > 0 and current_price < median_price * 0.6:
        fat_finger = True
        if not _is_on_cooldown(item_id, "fat_finger"):
            discount = (1 - current_price / median_price) * 100
            alerts.append({
                "level": "fun",
                "type": "fat_finger",
                "item_name": item_name,
                "price": current_price,
                "median_price": median_price,
                "discount": discount,
            })
            _set_cooldown(item_id, "fat_finger")

    # 신저가 (파격세일이면 스킵 - 실수 거래는 시세에 의미 없음)
    if not fat_finger:
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

    elif t == "fat_finger":
        price = alert["price"]
        median = alert["median_price"]
        discount = alert["discount"]
        embed = discord.Embed(
            title=f"🚨 [파격세일] {name} {discount:.0f}% OFF!!",
            description=(
                f"누군가 **{int(price):,}G**에 올렸습니다\n"
                f"시세 중앙값 {int(median):,}G\n\n"
                f"0 빼먹은 거 아닌지 의심됩니다...\n"
                f"눈치 빠른 모험가에게는 로또일 수도?"
            ),
            color=0xFEE75C
        )

    elif t == "price_above":
        price = alert["price"]
        target = alert["target"]
        embed = discord.Embed(
            title=f"[지정가] {name} 목표가 돌파!",
            description=(
                f"현재가 **{int(price):,}G**\n"
                f"설정가 {int(target):,}G 이상 도달\n\n"
                f"이 알림은 자동으로 해제됩니다."
            ),
            color=0xFF6348
        )

    elif t == "price_below":
        price = alert["price"]
        target = alert["target"]
        embed = discord.Embed(
            title=f"[지정가] {name} 지지선 이탈!",
            description=(
                f"현재가 **{int(price):,}G**\n"
                f"설정가 {int(target):,}G 이하로 하락\n\n"
                f"이 알림은 자동으로 해제됩니다."
            ),
            color=0x3498FF
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


# ─── 사용자별 DM 알림 ───

# 사용자별 쿨다운: {(user_id, item_id, event_type): datetime}
_user_cooldowns: dict[tuple[int, str, str], datetime] = {}
USER_COOLDOWN_MINUTES = 60


def _is_user_on_cooldown(user_id: int, item_id: str, event_type: str) -> bool:
    key = (user_id, item_id, event_type)
    last = _user_cooldowns.get(key)
    if last is None:
        return False
    return datetime.now(KST) - last < timedelta(minutes=USER_COOLDOWN_MINUTES)


def _set_user_cooldown(user_id: int, item_id: str, event_type: str):
    _user_cooldowns[(user_id, item_id, event_type)] = datetime.now(KST)


async def process_user_alerts_for_item(
    bot, item_id: str, item_name: str
):
    """사용자별 커스텀 알림 체크 및 DM 발송"""
    try:
        user_alerts = await get_all_user_alerts_for_item(item_id)
        if not user_alerts:
            return

        now = datetime.now(KST)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # 공통 데이터 1회만 조회
        h1_start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        h1_records = await get_price_history(item_id, h1_start, now_str)

        d14_start = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        d14_records = await get_price_history(item_id, d14_start, now_str)

        d1_start = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        d1_records = await get_price_history(item_id, d1_start, now_str)

        # 현재가
        current_price = None
        if d14_records:
            current_price = d14_records[-1]["unit_price"]

        # 1시간 변동률
        change_pct = None
        if h1_records and len(h1_records) >= 2:
            first = h1_records[0]["unit_price"]
            last = h1_records[-1]["unit_price"]
            if first > 0:
                change_pct = (last - first) / first * 100

        # 가격 범위
        all_prices = [r["unit_price"] for r in d14_records] if d14_records else []
        past_prices = all_prices[:-1] if len(all_prices) > 1 else []

        # 거래량
        vol_1h = sum(r["count"] for r in h1_records) if h1_records else 0
        vol_24h = sum(r["count"] for r in d1_records) if d1_records else 0
        avg_hourly = vol_24h / 24 if vol_24h > 0 else 0

        # RSI
        rsi = None
        if d14_records and len(d14_records) >= 10:
            ohlc = aggregate_to_ohlc(d14_records, interval_minutes=1440)
            if len(ohlc) >= 5:
                rsi = calc_rsi(ohlc["close"])

        # 사용자별로 그룹핑
        user_groups = {}
        for ua in user_alerts:
            user_groups.setdefault(ua["user_id"], []).append(ua)

        for user_id, alerts in user_groups.items():
            dm_alerts = []

            for ua in alerts:
                at = ua["alert_type"]
                tv = ua["threshold_value"]

                if _is_user_on_cooldown(user_id, item_id, at):
                    continue

                triggered = False
                alert_data = {"type": at, "item_name": item_name}

                if at == "surge" and change_pct is not None:
                    if change_pct >= tv:
                        alert_data.update(change_pct=change_pct, price=current_price)
                        triggered = True

                elif at == "crash" and change_pct is not None:
                    if change_pct <= -tv:
                        alert_data.update(change_pct=change_pct, price=current_price)
                        triggered = True

                elif at == "new_high" and current_price and past_prices:
                    # tv = 기간(일), d14_records에서 tv일 범위만 사용
                    window = [r["unit_price"] for r in d14_records
                              if r["sold_date"] >= (now - timedelta(days=int(tv))).strftime("%Y-%m-%d %H:%M:%S")]
                    if len(window) > 1 and current_price > max(window[:-1]):
                        alert_data.update(
                            price=current_price,
                            prev_high=max(window[:-1])
                        )
                        triggered = True

                elif at == "new_low" and current_price and past_prices:
                    window = [r["unit_price"] for r in d14_records
                              if r["sold_date"] >= (now - timedelta(days=int(tv))).strftime("%Y-%m-%d %H:%M:%S")]
                    if len(window) > 1 and current_price < min(window[:-1]):
                        alert_data.update(
                            price=current_price,
                            prev_low=min(window[:-1])
                        )
                        triggered = True

                elif at == "volume_spike" and avg_hourly > 0:
                    if vol_1h >= avg_hourly * tv:
                        alert_data.update(
                            vol_1h=vol_1h, avg_hourly=avg_hourly
                        )
                        triggered = True

                elif at == "rsi_upper" and rsi is not None:
                    if rsi > tv:
                        alert_data.update(rsi=rsi)
                        alert_data["type"] = "rsi_overbought"
                        triggered = True

                elif at == "rsi_lower" and rsi is not None:
                    if rsi < tv:
                        alert_data.update(rsi=rsi)
                        alert_data["type"] = "rsi_oversold"
                        triggered = True

                elif at == "price_above" and current_price is not None:
                    if current_price >= tv:
                        alert_data.update(
                            price=current_price, target=tv
                        )
                        triggered = True

                elif at == "price_below" and current_price is not None:
                    if current_price <= tv:
                        alert_data.update(
                            price=current_price, target=tv
                        )
                        triggered = True

                if triggered:
                    dm_alerts.append(alert_data)
                    _set_user_cooldown(user_id, item_id, at)

                    # 1회성 알림이면 자동 해제
                    if ua.get("one_time", 0):
                        await disable_user_alert(user_id, item_id, at)

            # DM 발송
            if dm_alerts:
                try:
                    user = await bot.fetch_user(user_id)
                    for alert in dm_alerts:
                        embed = build_alert_embed(alert)
                        embed.set_footer(text="개인 알림 설정 | /알림설정으로 변경")
                        await user.send(embed=embed)
                        logger.info(
                            f"DM 알림 발송: user={user_id}, "
                            f"{item_name} - {alert['type']}"
                        )
                except discord.Forbidden:
                    logger.warning(
                        f"DM 발송 실패 (DM 비활성): user={user_id}"
                    )
                except Exception as e:
                    logger.error(
                        f"DM 알림 발송 오류: user={user_id}, {e}"
                    )

    except Exception as e:
        logger.error(f"사용자별 알림 처리 오류 ({item_name}): {e}")
