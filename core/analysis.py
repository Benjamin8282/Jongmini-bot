import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


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


def _calc_vol_direction(volumes: pd.Series) -> bool | None:
    """최근 5캔들 평균 거래량이 이전 5캔들보다 높은지 판단. 데이터 부족 시 None."""
    if len(volumes) < 10:
        return None
    return volumes.iloc[-5:].mean() > volumes.iloc[-10:-5].mean()


_DIVERGENCE_MAP = {
    (True, False): "price_up_vol_down",
    (False, True): "price_down_vol_up",
}


def calc_price_volume_divergence(closes: pd.Series, volumes: pd.Series) -> str | None:
    """가격-거래량 괴리 감지. 최근 5캔들 기준."""
    if len(closes) < 6 or len(volumes) < 6:
        return None
    price_up = closes.iloc[-1] > closes.iloc[-6]
    vol_up = _calc_vol_direction(volumes)
    if vol_up is None:
        return None
    return _DIVERGENCE_MAP.get((price_up, vol_up))


def _interpret_correlation(corr: float) -> str:
    """상관계수 해석 텍스트 반환."""
    if abs(corr) >= 0.7:
        if corr > 0:
            return "강한 양의 상관 (같이 오르내림)"
        return "강한 음의 상관 (반대로 움직임)"
    if abs(corr) >= 0.3:
        if corr > 0:
            return "약한 양의 상관"
        return "약한 음의 상관"
    return "상관 없음 (독립적으로 움직임)"


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
    return {
        "correlation": corr,
        "overlap_count": overlap,
        "interpretation": _interpret_correlation(corr),
    }


def _calc_trend_score(ma_status: str) -> int:
    """추세 점수 산출."""
    trend_scores = {"bullish": 2, "bearish": -2}
    return trend_scores.get(ma_status, 0)


def _calc_rsi_score(rsi: float | None) -> int:
    """RSI 점수 산출."""
    if rsi is None:
        return 0
    if rsi < 30:
        return 1
    if rsi > 70:
        return -1
    return 0


def _calc_surge_trend_score(vol_info: dict, ma_status: str) -> int:
    """거래량 급증 시 추세 방향에 따른 점수 산출."""
    if not vol_info["surge"]:
        return 0
    surge_scores = {"bullish": 1, "bearish": -1}
    return surge_scores.get(ma_status, 0)


def _calc_volume_divergence_score(divergence: str | None, vol_info: dict, ma_status: str) -> int:
    """거래량-가격 일치/괴리 점수 산출."""
    divergence_scores = {
        "price_up_vol_down": -1,
        "price_down_vol_up": 1,
    }
    if divergence in divergence_scores:
        return divergence_scores[divergence]
    return _calc_surge_trend_score(vol_info, ma_status)


def _calc_disparity_score(disparity: float | None) -> int:
    """이격도 과열/과냉 점수 산출."""
    if disparity is None or abs(disparity) < 10:
        return 0
    return -1 if disparity > 0 else 1


def _score_to_opinion(score: int) -> str:
    """점수를 종합 의견 텍스트로 변환."""
    if score >= 3:
        return "강한 매수 신호"
    if score >= 1:
        return "매수 우위"
    if score == 0:
        return "관망"
    if score >= -2:
        return "매도 우위"
    return "강한 매도 신호"


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
    score = (
        _calc_trend_score(ma_info["status"])
        + _calc_rsi_score(rsi)
        + _calc_volume_divergence_score(divergence, vol_info, ma_info["status"])
        + _calc_disparity_score(disparity)
    )

    return {
        "score": score,
        "opinion": _score_to_opinion(score),
        "rsi": rsi,
        "ma": ma_info,
        "disparity": disparity,
        "volume": vol_info,
        "divergence": divergence,
    }


def _format_trend_section(ma: dict) -> list[str]:
    """추세 섹션 포맷."""
    status_map = {
        "bullish": (
            "**추세: 상승추세 (정배열)**",
            "→ 단기·중기·장기 평균가가 순서대로 높아,\n"
            "　 가격이 꾸준히 오르는 흐름입니다."
        ),
        "bearish": (
            "**추세: 하락추세 (역배열)**",
            "→ 단기·중기·장기 평균가가 순서대로 낮아,\n"
            "　 가격이 꾸준히 떨어지는 흐름입니다."
        ),
        "neutral": (
            "**추세: 횡보 (혼조)**",
            "→ 평균가들이 뒤섞여 있어 뚜렷한 방향이 없습니다.\n"
            "　 당분간 가격이 오르내리며 눈치를 보는 구간입니다."
        ),
    }
    default = (
        "**추세: 데이터 부족**",
        "→ 캔들이 20개 이상 쌓이면 추세를 판단할 수 있습니다."
    )
    title, desc = status_map.get(ma["status"], default)
    return [title, desc, ""]


def _format_rsi_section(rsi: float | None) -> list[str]:
    """RSI 섹션 포맷."""
    if rsi is None:
        return ["**RSI: 데이터 부족**", "→ 캔들이 15개 이상 쌓이면 계산됩니다.", ""]
    if rsi > 70:
        label = "과매수"
        desc = ("→ 최근 사려는 힘이 너무 강했습니다.\n"
                "　 너무 올라서 곧 떨어질 수 있으니 주의하세요.")
    elif rsi < 30:
        label = "과매도"
        desc = ("→ 최근 팔려는 힘이 너무 강했습니다.\n"
                "　 너무 떨어져서 반등할 가능성이 있습니다.")
    else:
        label = "중립"
        desc = ("→ 사려는 사람과 팔려는 사람의 힘이 비슷합니다.\n"
                "　 70 이상이면 과열, 30 이하면 침체 신호입니다.")
    return [f"**RSI(14): {rsi:.1f} ({label})**", desc, ""]


def _format_volume_section(vol: dict) -> list[str]:
    """거래량 섹션 포맷."""
    if vol["ratio"] is None:
        return ["**거래량: 데이터 부족**"]
    pct = int(vol["ratio"] * 100)
    if vol["surge"]:
        return [
            f"**거래량: 평균 대비 {pct}% (급증)**",
            "→ 평소보다 거래가 훨씬 활발합니다.\n"
            "　 큰 가격 변동이 올 수 있는 구간입니다."
        ]
    return [
        f"**거래량: 평균 대비 {pct}% (보통)**",
        "→ 거래량이 평소 수준입니다."
    ]


def _format_divergence_section(div: str | None) -> list[str]:
    """괴리 섹션 포맷."""
    divergence_texts = {
        "price_up_vol_down": (
            "\n**주의: 가격은 오르는데 거래량은 줄고 있습니다.**\n"
            "→ 상승 힘이 약해지고 있어 곧 꺾일 수 있습니다."
        ),
        "price_down_vol_up": (
            "\n**주의: 가격은 떨어지는데 거래량은 늘고 있습니다.**\n"
            "→ 바닥을 다지는 중일 수 있어 반등 가능성이 있습니다."
        ),
    }
    text = divergence_texts.get(div)
    return [text] if text else []


def _format_disparity_section(disp: float | None) -> list[str]:
    """이격도 섹션 포맷."""
    lines = [""]
    if disp is None:
        return lines
    arrow = "+" if disp > 0 else ""
    lines.append(f"**이격도: {arrow}{disp:.1f}%**")
    if abs(disp) >= 10:
        lines.append(
            "→ 현재 가격이 평균에서 많이 벗어났습니다.\n"
            "　 평균 가격으로 되돌아올 가능성이 높습니다."
        )
    else:
        lines.append("→ 현재 가격이 평균 근처에 있어 안정적입니다.")
    return lines


def _format_summary_section(score: int) -> list[str]:
    """요약 섹션 포맷."""
    summaries = {
        "strong_buy": (
            "여러 지표가 상승을 가리키고 있습니다.\n"
            "매수하기 좋은 타이밍이지만, 급등 후에는 조정이 올 수 있으니\n"
            "RSI와 거래량 변화를 계속 지켜보세요."
        ),
        "buy": (
            "전반적으로 오름세입니다.\n"
            "지금 사도 괜찮지만, RSI가 70에 가까워지면 주의하세요."
        ),
        "neutral": (
            "뚜렷한 방향이 없는 구간입니다.\n"
            "섣불리 움직이기보다 추세가 잡힐 때까지 지켜보세요."
        ),
        "sell": (
            "전반적으로 내림세입니다.\n"
            "매수는 신중하게, RSI가 30 아래로 내려가면 반등을 노려볼 수 있습니다."
        ),
        "strong_sell": (
            "여러 지표가 하락을 가리키고 있습니다.\n"
            "지금은 관망하면서 바닥 신호(RSI 30 이하, 거래량 급증)를\n"
            "기다리는 것이 안전합니다."
        ),
    }
    key = _score_to_summary_key(score)
    return ["", "**요약**", summaries[key]]


def _score_to_summary_key(score: int) -> str:
    """점수를 요약 키로 변환."""
    if score >= 3:
        return "strong_buy"
    if score >= 1:
        return "buy"
    if score == 0:
        return "neutral"
    if score >= -2:
        return "sell"
    return "strong_sell"


def format_analysis_text(result: dict) -> str:
    """분석 결과를 친절한 한국어 텍스트로 포맷."""
    score = result["score"]
    opinion = result["opinion"]

    lines = [
        f"**종합 의견: {opinion} ({score:+d}점)**",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    lines.extend(_format_trend_section(result["ma"]))
    lines.extend(_format_rsi_section(result["rsi"]))
    lines.extend(_format_volume_section(result["volume"]))
    lines.extend(_format_divergence_section(result["divergence"]))
    lines.extend(_format_disparity_section(result["disparity"]))
    lines.extend(_format_summary_section(score))

    return "\n".join(lines)


def _find_recent_records(records: list[dict], now: datetime) -> tuple[list[dict], int]:
    """최근 데이터를 시간 범위별로 탐색. (recent, used_hours) 반환."""
    for hours in [24, 48, 96, 168]:
        cutoff = (now - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        recent = [r for r in records if r["sold_date"] >= cutoff]
        if len(recent) >= 20:
            return recent, hours
    return records, 0


def _calc_iqr_bounds(price_arr: np.ndarray) -> tuple[float, float]:
    """IQR 기반 이상치 제거 경계값 계산."""
    q1 = float(np.percentile(price_arr, 25))
    q3 = float(np.percentile(price_arr, 75))
    iqr = q3 - q1
    median_val = float(np.median(price_arr))

    if iqr > 0:
        return q1 - 1.5 * iqr, q3 + 1.5 * iqr
    if median_val > 0:
        return median_val * 0.5, median_val * 2.0
    return 0, float("inf")


def _build_weighted_prices(recent: list[dict], lower: float, upper: float) -> list[float]:
    """거래량(count) 가중 가격 배열 생성 (price == 0 및 이상치 제외)."""
    weighted_prices = []
    for r in recent:
        p = r["unit_price"]
        if p > 0 and lower <= p <= upper:
            count = max(r.get("count", 1), 1)
            weighted_prices.extend([p] * count)
    return weighted_prices


def recommend_prices(records: list[dict]) -> dict | None:
    """
    거래 기록 기반 판매 추천 가격 산출.

    최근 거래 데이터에서 거래량 가중 백분위수로 3단계 가격을 추천:
    - safe (P60): 팔릴만한 중간 가격
    - optimal (P80): 팔릴만한 최대 가격
    - ambitious (P95): 걸어볼만한 가격
    """
    if not records:
        return None

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)

    recent, used_hours = _find_recent_records(records, now)

    if len(recent) < 10:
        return None

    price_arr = np.array([r["unit_price"] for r in recent], dtype=float)
    lower, upper = _calc_iqr_bounds(price_arr)

    weighted_prices = _build_weighted_prices(recent, lower, upper)

    if len(weighted_prices) < 10:
        logger.debug(
            "추천가 산출 불가: 필터 후 거래량 %d건 (원본 %d건)",
            len(weighted_prices), len(recent)
        )
        return None

    arr = np.array(weighted_prices)

    return {
        "safe": int(np.percentile(arr, 60)),
        "optimal": int(np.percentile(arr, 80)),
        "ambitious": int(np.percentile(arr, 95)),
        "median": int(np.median(arr)),
        "sample_size": len(recent),
        "total_volume": len(weighted_prices),
        "used_hours": used_hours,
    }


def format_recommendation_text(rec: dict) -> str:
    """추천 가격을 한국어 텍스트로 포맷."""
    lines = []

    lines.append(f"**팔릴만한 중간 가격: {rec['safe']:,}**")
    lines.append(
        "→ 최근 거래의 상위 40% 수준.\n"
        "　 빠르게 팔고 싶을 때 적정한 가격입니다."
    )
    lines.append("")

    lines.append(f"**팔릴만한 최대 가격: {rec['optimal']:,}**")
    lines.append(
        "→ 상위 20% 수준.\n"
        "　 조금 기다리면 충분히 팔릴 가격입니다."
    )
    lines.append("")

    lines.append(f"**걸어볼만한 가격: {rec['ambitious']:,}**")
    lines.append(
        "→ 상위 5% 수준.\n"
        "　 안 팔릴 수도 있지만 걸어볼 만합니다."
    )
    lines.append("")

    # 데이터 기반 정보
    if rec["used_hours"] > 0:
        period_text = f"최근 {rec['used_hours']}시간"
    else:
        period_text = "전체 기간"
    lines.append(
        f"*{period_text} 거래 {rec['sample_size']}건"
        f" (총 {rec['total_volume']:,}개) 기반*"
    )

    return "\n".join(lines)
