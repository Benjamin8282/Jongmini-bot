import pandas as pd


def calc_rsi(closes: pd.Series, period: int = 14) -> float | None:
    """RSI(상대강도지수) 계산. 데이터 부족 시 None 반환."""
    if len(closes) < period + 1:
        return None
    delta = closes.diff().dropna()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window=period).mean().iloc[-1]
    avg_loss = loss.rolling(window=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_ma_alignment(closes: pd.Series) -> dict:
    """MA5/MA10/MA20 배열 상태 판단."""
    result = {"status": "unknown", "ma5": None, "ma10": None, "ma20": None}
    if len(closes) < 20:
        return result

    ma5 = closes.iloc[-5:].mean()
    ma10 = closes.iloc[-10:].mean()
    ma20 = closes.iloc[-20:].mean()
    result["ma5"] = ma5
    result["ma10"] = ma10
    result["ma20"] = ma20

    if ma5 > ma10 > ma20:
        result["status"] = "bullish"
    elif ma5 < ma10 < ma20:
        result["status"] = "bearish"
    else:
        result["status"] = "neutral"
    return result


def calc_ma_disparity(current_price: float, ma20: float | None) -> float | None:
    """MA20 대비 이격도(%) 계산."""
    if ma20 is None or ma20 == 0:
        return None
    return (current_price - ma20) / ma20 * 100


def calc_volume_surge(volumes: pd.Series) -> dict:
    """거래량 급증 여부 판단. 최근 5캔들 평균 vs 20캔들 평균."""
    result = {"ratio": None, "surge": False}
    if len(volumes) < 20:
        return result
    avg5 = volumes.iloc[-5:].mean()
    avg20 = volumes.iloc[-20:].mean()
    if avg20 == 0:
        return result
    ratio = avg5 / avg20
    result["ratio"] = ratio
    result["surge"] = ratio >= 1.5
    return result


def calc_price_volume_divergence(closes: pd.Series, volumes: pd.Series) -> str | None:
    """가격-거래량 괴리 감지. 최근 5캔들 기준."""
    if len(closes) < 6 or len(volumes) < 6:
        return None
    price_up = closes.iloc[-1] > closes.iloc[-6]
    vol_up = volumes.iloc[-5:].mean() > volumes.iloc[-10:-5].mean() if len(volumes) >= 10 else None
    if vol_up is None:
        return None
    if price_up and not vol_up:
        return "price_up_vol_down"
    elif not price_up and vol_up:
        return "price_down_vol_up"
    return None


def calc_correlation(closes_a: pd.Series, closes_b: pd.Series,
                     min_overlap: int = 10) -> dict:
    """두 종가 시계열의 피어슨 상관계수 계산."""
    merged = pd.concat([closes_a, closes_b], axis=1, join="inner")
    merged.columns = ["a", "b"]
    overlap = len(merged)

    if overlap < min_overlap:
        return {
            "correlation": None,
            "overlap_count": overlap,
            "interpretation": None,
        }

    corr = merged["a"].corr(merged["b"])
    if abs(corr) >= 0.7:
        interp = "강한 양의 상관 (같이 오르내림)" if corr > 0 else "강한 음의 상관 (반대로 움직임)"
    elif abs(corr) >= 0.3:
        interp = "약한 양의 상관" if corr > 0 else "약한 음의 상관"
    else:
        interp = "상관 없음 (독립적으로 움직임)"

    return {
        "correlation": corr,
        "overlap_count": overlap,
        "interpretation": interp,
    }


def analyze(ohlc_df: pd.DataFrame) -> dict:
    """OHLC DataFrame을 분석하여 종합 의견 생성."""
    closes = ohlc_df["close"]
    volumes = ohlc_df["volume"]
    current_price = float(closes.iloc[-1])

    # 각 지표 계산
    rsi = calc_rsi(closes)
    ma_info = calc_ma_alignment(closes)
    disparity = calc_ma_disparity(current_price, ma_info["ma20"])
    vol_info = calc_volume_surge(volumes)
    divergence = calc_price_volume_divergence(closes, volumes)

    # 점수 산출
    score = 0

    # 추세 점수
    if ma_info["status"] == "bullish":
        score += 2
    elif ma_info["status"] == "bearish":
        score -= 2

    # RSI 점수
    if rsi is not None:
        if rsi < 30:
            score += 1
        elif rsi > 70:
            score -= 1

    # 거래량-가격 일치/괴리
    if divergence == "price_up_vol_down":
        score -= 1
    elif divergence == "price_down_vol_up":
        score += 1
    elif vol_info["surge"] and ma_info["status"] == "bullish":
        score += 1
    elif vol_info["surge"] and ma_info["status"] == "bearish":
        score -= 1

    # 이격도 과열/과냉
    if disparity is not None and abs(disparity) >= 10:
        if disparity > 0:
            score -= 1
        else:
            score += 1

    # 종합 의견
    if score >= 3:
        opinion = "강한 매수 신호"
    elif score >= 1:
        opinion = "매수 우위"
    elif score == 0:
        opinion = "관망"
    elif score >= -2:
        opinion = "매도 우위"
    else:
        opinion = "강한 매도 신호"

    return {
        "score": score,
        "opinion": opinion,
        "rsi": rsi,
        "ma": ma_info,
        "disparity": disparity,
        "volume": vol_info,
        "divergence": divergence,
    }


def format_analysis_text(result: dict) -> str:
    """분석 결과를 친절한 한국어 텍스트로 포맷."""
    lines = []

    score = result["score"]
    opinion = result["opinion"]
    lines.append(f"**종합 의견: {opinion} ({score:+d}점)**")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # 추세
    ma = result["ma"]
    if ma["status"] == "bullish":
        lines.append("**추세: 상승추세 (정배열)**")
        lines.append(
            "→ 단기·중기·장기 평균가가 순서대로 높아,\n"
            "　 가격이 꾸준히 오르는 흐름입니다."
        )
    elif ma["status"] == "bearish":
        lines.append("**추세: 하락추세 (역배열)**")
        lines.append(
            "→ 단기·중기·장기 평균가가 순서대로 낮아,\n"
            "　 가격이 꾸준히 떨어지는 흐름입니다."
        )
    elif ma["status"] == "neutral":
        lines.append("**추세: 횡보 (혼조)**")
        lines.append(
            "→ 평균가들이 뒤섞여 있어 뚜렷한 방향이 없습니다.\n"
            "　 당분간 가격이 오르내리며 눈치를 보는 구간입니다."
        )
    else:
        lines.append("**추세: 데이터 부족**")
        lines.append("→ 캔들이 20개 이상 쌓이면 추세를 판단할 수 있습니다.")

    lines.append("")

    # RSI
    rsi = result["rsi"]
    if rsi is not None:
        if rsi > 70:
            lines.append(f"**RSI(14): {rsi:.1f} (과매수)**")
            lines.append(
                "→ 최근 사려는 힘이 너무 강했습니다.\n"
                "　 너무 올라서 곧 떨어질 수 있으니 주의하세요."
            )
        elif rsi < 30:
            lines.append(f"**RSI(14): {rsi:.1f} (과매도)**")
            lines.append(
                "→ 최근 팔려는 힘이 너무 강했습니다.\n"
                "　 너무 떨어져서 반등할 가능성이 있습니다."
            )
        else:
            lines.append(f"**RSI(14): {rsi:.1f} (중립)**")
            lines.append(
                "→ 사려는 사람과 팔려는 사람의 힘이 비슷합니다.\n"
                "　 70 이상이면 과열, 30 이하면 침체 신호입니다."
            )
    else:
        lines.append("**RSI: 데이터 부족**")
        lines.append("→ 캔들이 15개 이상 쌓이면 계산됩니다.")

    lines.append("")

    # 거래량
    vol = result["volume"]
    if vol["ratio"] is not None:
        pct = int(vol["ratio"] * 100)
        if vol["surge"]:
            lines.append(f"**거래량: 평균 대비 {pct}% (급증)**")
            lines.append(
                "→ 평소보다 거래가 훨씬 활발합니다.\n"
                "　 큰 가격 변동이 올 수 있는 구간입니다."
            )
        else:
            lines.append(f"**거래량: 평균 대비 {pct}% (보통)**")
            lines.append("→ 거래량이 평소 수준입니다.")
    else:
        lines.append("**거래량: 데이터 부족**")

    # 괴리
    div = result["divergence"]
    if div == "price_up_vol_down":
        lines.append(
            "\n**주의: 가격은 오르는데 거래량은 줄고 있습니다.**\n"
            "→ 상승 힘이 약해지고 있어 곧 꺾일 수 있습니다."
        )
    elif div == "price_down_vol_up":
        lines.append(
            "\n**주의: 가격은 떨어지는데 거래량은 늘고 있습니다.**\n"
            "→ 바닥을 다지는 중일 수 있어 반등 가능성이 있습니다."
        )

    lines.append("")

    # 이격도
    disp = result["disparity"]
    if disp is not None:
        arrow = "+" if disp > 0 else ""
        lines.append(f"**이격도: {arrow}{disp:.1f}%**")
        if abs(disp) >= 10:
            lines.append(
                "→ 현재 가격이 평균에서 많이 벗어났습니다.\n"
                "　 평균 가격으로 되돌아올 가능성이 높습니다."
            )
        else:
            lines.append("→ 현재 가격이 평균 근처에 있어 안정적입니다.")

    lines.append("")

    # 요약
    lines.append("**요약**")
    if score >= 3:
        lines.append(
            "여러 지표가 상승을 가리키고 있습니다.\n"
            "매수하기 좋은 타이밍이지만, 급등 후에는 조정이 올 수 있으니\n"
            "RSI와 거래량 변화를 계속 지켜보세요."
        )
    elif score >= 1:
        lines.append(
            "전반적으로 오름세입니다.\n"
            "지금 사도 괜찮지만, RSI가 70에 가까워지면 주의하세요."
        )
    elif score == 0:
        lines.append(
            "뚜렷한 방향이 없는 구간입니다.\n"
            "섣불리 움직이기보다 추세가 잡힐 때까지 지켜보세요."
        )
    elif score >= -2:
        lines.append(
            "전반적으로 내림세입니다.\n"
            "매수는 신중하게, RSI가 30 아래로 내려가면 반등을 노려볼 수 있습니다."
        )
    else:
        lines.append(
            "여러 지표가 하락을 가리키고 있습니다.\n"
            "지금은 관망하면서 바닥 신호(RSI 30 이하, 거래량 급증)를\n"
            "기다리는 것이 안전합니다."
        )

    return "\n".join(lines)
