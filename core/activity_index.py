import pandas as pd
import numpy as np

from core.db import get_basket_items, get_daily_volumes
from core.logger import logger


# ───────────────────────────────────────────
# Phase A: Hampel 필터
# ───────────────────────────────────────────

def _hampel_filter(
    series: pd.Series, window: int = 7, threshold: float = 3.0
) -> tuple[pd.Series, list]:
    """
    이동 중앙값 기반 스파이크 감지 및 교체.

    각 데이터 포인트를 주변 window 크기의 중앙값과 비교하여,
    MAD(Median Absolute Deviation) 기준 threshold배 이상
    벗어난 값을 로컬 중앙값으로 교체한다.

    이벤트성 급등락(강화 확률 이벤트 등) 제거에 효과적.
    """
    n = len(series)
    cleaned = series.copy()
    replaced = []
    k = 1.4826  # MAD → σ 변환 상수 (정규분포 가정)
    half_w = window // 2

    for i in range(half_w, n - half_w):
        window_data = series.iloc[i - half_w:i + half_w + 1]
        local_median = window_data.median()
        mad = np.median(np.abs(window_data - local_median))
        sigma_est = k * mad

        if sigma_est == 0:
            continue

        if np.abs(series.iloc[i] - local_median) > threshold * sigma_est:
            cleaned.iloc[i] = local_median
            replaced.append(series.index[i])

    return cleaned, replaced


# ───────────────────────────────────────────
# Phase B: STL 분해
# ───────────────────────────────────────────

def _stl_decompose(series: pd.Series, period: int = 7) -> pd.Series:
    """
    Seasonal-Trend decomposition using LOESS (STL).

    주기=7로 요일 효과(예: 주말 거래량 감소)를 분리하여
    trend + residual만 반환한다. robust=True로 이상치 영향 최소화.
    """
    from statsmodels.tsa.seasonal import STL

    if len(series) < period * 2:
        return series

    # STL은 결측 불가 → 선형 보간
    filled = series.interpolate(method="linear").ffill().bfill()

    try:
        stl = STL(filled, period=period, robust=True)
        result = stl.fit()
        return result.trend + result.resid
    except Exception as e:
        logger.warning(f"STL 분해 실패, 원본 사용: {e}")
        return series


# ───────────────────────────────────────────
# Phase C: MAD 이상치 감지
# ───────────────────────────────────────────

def _mad_outlier_detection(
    row: pd.Series, threshold: float = 3.0
) -> list[str]:
    """
    단일 날짜의 아이템별 정규화값에서 이상치 감지.

    일반적인 2σ 방식은 극단값이 σ를 부풀려 다른 이상치를
    가리는 '마스킹 효과'가 있다. MAD는 중앙값 기반이라
    이 문제에 강건하다.
    """
    row = row.dropna()
    if len(row) < 3:
        return []

    median_val = row.median()
    mad = np.median(np.abs(row - median_val))
    if mad == 0:
        return []

    k = 1.4826  # MAD → σ 변환
    sigma_est = k * mad

    outlier_items = []
    for item_name, val in row.items():
        if np.abs(val - median_val) > threshold * sigma_est:
            outlier_items.append(f"{item_name} ({val:.0f}%)")

    return outlier_items


# ───────────────────────────────────────────
# Phase D: PELT 변화점 탐지
# ───────────────────────────────────────────

def _detect_changepoints(
    series: pd.Series, min_size: int = 14, penalty: float = 5.0
) -> list:
    """
    Pruned Exact Linear Time (PELT) 알고리즘으로
    시계열의 통계적 체제 전환(regime shift) 시점을 탐지.

    시즌 업데이트로 아이템 수급 구조가 바뀌면
    거래량 기준선 자체가 달라지는데, 이를 자동 감지.

    penalty가 클수록 변화점을 적게 감지 (과적합 방지).
    min_size는 한 체제의 최소 길이 (14일 = 2주).
    """
    import ruptures as rpt

    values = series.dropna().values
    if len(values) < min_size * 2:
        return []

    try:
        algo = rpt.Pelt(model="rbf", min_size=min_size).fit(values)
        result = algo.predict(pen=penalty)

        # 마지막 인덱스(데이터 끝)는 제거
        valid_index = series.dropna().index
        cp_dates = []
        for idx in result:
            if idx < len(valid_index):
                cp_dates.append(valid_index[idx])

        return cp_dates
    except Exception as e:
        logger.warning(f"PELT 변화점 탐지 실패: {e}")
        return []


def _normalize_by_regime(
    series: pd.Series, changepoints: list, window: int = 30
) -> pd.Series:
    """
    체제(regime)별 이동평균 기준 정규화.

    변화점을 기준으로 데이터를 구간 분할한 뒤,
    각 구간 내의 이동평균을 100% 기준으로 정규화.
    체제 전환(시즌 업데이트 등) 전후의 기준선 차이를 보정.
    """
    if not changepoints or len(series) < window:
        ma = series.rolling(
            window=window, min_periods=max(window // 2, 1)
        ).mean()
        return series / ma * 100

    result = pd.Series(index=series.index, dtype=float)

    # 구간 경계 생성
    boundaries = (
        [series.index[0]] + sorted(changepoints) + [series.index[-1]]
    )

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        mask = (series.index >= start) & (series.index <= end)
        segment = series.loc[mask]

        if len(segment) < 3:
            result.loc[mask] = 100.0
            continue

        seg_window = min(window, max(len(segment) // 2, 3))
        ma = segment.rolling(
            window=seg_window, min_periods=max(seg_window // 2, 1)
        ).mean()
        result.loc[mask] = segment / ma * 100

    return result


# ───────────────────────────────────────────
# 메인 파이프라인
# ───────────────────────────────────────────

async def calc_activity_index(display_days: int = 30) -> dict | None:
    """
    노이즈 감소 파이프라인을 적용한 활동지수 산출.

    파이프라인:
        A) Hampel 필터 → 이벤트성 스파이크 제거
        B) STL 분해 → 요일 주기성 제거
        C) MAD 이상치 감지 → 잔여 이상치 플래그
        D) PELT 변화점 탐지 → 체제 전환 감지 및 구간별 정규화

    Returns:
        {
            "dates": [str, ...],
            "index": [float, ...],          # 정제된 활동지수
            "raw_index": [float, ...],      # 정제 전 원본 지수
            "item_count": int,
            "outliers": {date: [item_name, ...]},
            "changepoints": [date_str, ...],
            "hampel_stats": {
                "total_replaced": int,
                "items": {name: count}
            },
        }
        또는 데이터 부족 시 None
    """
    basket = await get_basket_items()
    if len(basket) < 3:
        return None

    # 이동평균 + PELT 여유분 확보
    fetch_days = display_days + 60

    # ── 1단계: 일별 거래량 수집 ──
    all_series = {}
    for item in basket:
        rows = await get_daily_volumes(item["item_id"], fetch_days)
        if not rows:
            continue
        series = pd.Series(
            {r["date"]: r["volume"] for r in rows},
            dtype=float,
        )
        series.index = pd.to_datetime(series.index)
        all_series[item["item_name"]] = series

    if len(all_series) < 3:
        return None

    # 전체 날짜 범위 통합
    all_dates = sorted(
        set().union(*(s.index for s in all_series.values()))
    )
    df_raw = pd.DataFrame(index=all_dates)
    for name, series in all_series.items():
        df_raw[name] = series
    df_raw = df_raw.sort_index()

    # ── Phase A: Hampel 필터 ──
    logger.info("활동지수 Phase A: Hampel 필터 적용")
    df_hampel = pd.DataFrame(index=df_raw.index)
    hampel_stats = {"total_replaced": 0, "items": {}}

    for col in df_raw.columns:
        col_data = df_raw[col].dropna()
        if len(col_data) < 15:
            df_hampel[col] = df_raw[col]
            continue

        cleaned, replaced = _hampel_filter(
            col_data, window=7, threshold=3.0
        )
        df_hampel[col] = df_raw[col].copy()
        df_hampel.loc[cleaned.index, col] = cleaned

        if replaced:
            hampel_stats["total_replaced"] += len(replaced)
            hampel_stats["items"][col] = len(replaced)

    if hampel_stats["total_replaced"] > 0:
        logger.info(
            f"Hampel 필터: {hampel_stats['total_replaced']}개 "
            f"스파이크 교체 ({hampel_stats['items']})"
        )

    # ── Phase B: STL 분해 (요일 효과 제거) ──
    logger.info("활동지수 Phase B: STL 분해 적용")
    df_deseason = pd.DataFrame(index=df_hampel.index)

    for col in df_hampel.columns:
        col_data = df_hampel[col].dropna()
        if len(col_data) < 14:
            df_deseason[col] = df_hampel[col]
            continue
        decomposed = _stl_decompose(col_data, period=7)
        df_deseason[col] = df_hampel[col].copy()
        df_deseason.loc[decomposed.index, col] = decomposed

    # ── Phase D: PELT 변화점 탐지 (정규화 전) ──
    logger.info("활동지수 Phase D: PELT 변화점 탐지")
    temp_median = df_deseason.median(axis=1).dropna()
    changepoint_dates = _detect_changepoints(
        temp_median, min_size=14, penalty=5.0
    )
    if changepoint_dates:
        cp_str = [d.strftime("%Y-%m-%d") for d in changepoint_dates]
        logger.info(f"변화점 감지: {cp_str}")

    # ── 정규화: 체제별 이동평균 대비 비율(%) ──
    normalized = pd.DataFrame(index=df_deseason.index)
    for col in df_deseason.columns:
        col_data = df_deseason[col].dropna()
        if len(col_data) < 15:
            continue
        normalized[col] = _normalize_by_regime(
            col_data, changepoint_dates, window=30
        )

    # 원본 지수 (정제 전 비교용)
    raw_normalized = pd.DataFrame(index=df_raw.index)
    for col in df_raw.columns:
        ma30 = df_raw[col].rolling(window=30, min_periods=15).mean()
        raw_normalized[col] = df_raw[col] / ma30 * 100

    # 표시 기간만 잘라내기
    normalized = normalized.iloc[-display_days:]
    normalized = normalized.dropna(how="all")
    raw_normalized = raw_normalized.iloc[-display_days:]
    raw_normalized = raw_normalized.dropna(how="all")

    if normalized.empty:
        return None

    # ── 일별 중앙값 = 활동지수 ──
    daily_median = normalized.median(axis=1)
    raw_daily_median = raw_normalized.median(axis=1)

    # ── Phase C: MAD 이상치 감지 ──
    logger.info("활동지수 Phase C: MAD 이상치 감지")
    outliers = {}
    for date_idx in normalized.index:
        row = normalized.loc[date_idx]
        outlier_items = _mad_outlier_detection(row, threshold=3.0)
        if outlier_items:
            date_str = date_idx.strftime("%Y-%m-%d")
            outliers[date_str] = outlier_items

    # 결과 조립
    dates = [d.strftime("%Y-%m-%d") for d in daily_median.index]
    index_values = [round(v, 1) for v in daily_median.values]

    raw_reindexed = raw_daily_median.reindex(daily_median.index)
    raw_values = [
        round(v, 1) if not np.isnan(v) else 100.0
        for v in raw_reindexed.values
    ]

    cp_strs = [
        d.strftime("%Y-%m-%d") for d in changepoint_dates
        if len(daily_median.index) > 0 and d >= daily_median.index[0]
    ]

    logger.info(
        f"활동지수 산출 완료: {len(dates)}일, "
        f"이상치 {len(outliers)}건, 변화점 {len(cp_strs)}건"
    )

    return {
        "dates": dates,
        "index": index_values,
        "raw_index": raw_values,
        "item_count": len(all_series),
        "outliers": outliers,
        "changepoints": cp_strs,
        "hampel_stats": hampel_stats,
    }
