import pandas as pd
import numpy as np

from core.db import get_all_watch_items, get_basket_items, get_daily_volumes
from core.logger import logger

# 정규화에 필요한 아이템별 최소 관측 일수
MIN_OBSERVATIONS = 15

# 지수 산출에 필요한 최소 아이템 수 (중앙값의 의미 보장)
MIN_BASKET_ITEMS = 3

# 앵커 기준선 기간 (일). 조회 옵션(days)과 무관하게 고정하여
# 같은 날짜의 지수가 어떤 days로 조회해도 동일한 값이 되도록 한다.
BASELINE_DAYS = 90


# ───────────────────────────────────────────
# Phase A: Hampel 스파이크 감지 (플래그 전용)
# ───────────────────────────────────────────

def _hampel_filter(
    series: pd.Series, window: int = 7, threshold: float = 3.0
) -> tuple[pd.Series, list]:
    """
    이동 중앙값 기반 스파이크 감지.

    각 데이터 포인트를 주변 window 크기의 중앙값과 비교하여,
    MAD(Median Absolute Deviation) 기준 threshold배 이상
    벗어난 값을 감지한다.

    활동지수에서 급증은 제거할 노이즈가 아니라 포착할 신호이므로
    cleaned(치환본)는 지수 산출에 사용하지 않고,
    감지된 날짜 목록(replaced)만 플래그로 활용한다.
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


def _detect_spikes(df_raw: pd.DataFrame) -> dict:
    """Phase A: Hampel 스파이크 감지를 각 컬럼에 적용 (플래그만, 치환 없음)."""
    logger.info("활동지수 Phase A: Hampel 스파이크 감지")
    spike_stats = {"total_flagged": 0, "items": {}}

    for col in df_raw.columns:
        col_data = df_raw[col].dropna()
        if len(col_data) < MIN_OBSERVATIONS:
            continue
        _, flagged = _hampel_filter(col_data, window=7, threshold=3.0)
        if flagged:
            spike_stats["total_flagged"] += len(flagged)
            spike_stats["items"][col] = len(flagged)

    if spike_stats["total_flagged"] > 0:
        logger.info(
            f"Hampel 감지: {spike_stats['total_flagged']}개 "
            f"이벤트성 급변 플래그 ({spike_stats['items']})"
        )

    return spike_stats


# ───────────────────────────────────────────
# Phase B: STL 분해
# ───────────────────────────────────────────

def _stl_decompose(series: pd.Series, period: int = 7) -> pd.Series:
    """
    Seasonal-Trend decomposition using LOESS (STL).

    주기=7로 요일 효과(예: 주말 거래량 감소)를 분리하여
    trend + residual만 반환한다. robust=True로 이상치 영향 최소화.

    입력은 달력 기준 등간격(일 단위) 시계열이어야 요일 정렬이 유지된다.
    거래량은 음수가 될 수 없으므로 결과를 0 하한으로 클리핑한다.
    """
    from statsmodels.tsa.seasonal import STL

    if len(series) < period * 2:
        return series

    try:
        stl = STL(series, period=period, robust=True)
        result = stl.fit()
        return (result.trend + result.resid).clip(lower=0.0)
    except Exception as e:
        logger.warning(f"STL 분해 실패, 원본 사용: {e}")
        return series


def _apply_stl_to_column(df_raw: pd.DataFrame, df_deseason: pd.DataFrame, col: str):
    """단일 컬럼에 STL 분해 적용.

    STL은 등간격·결측 없는 입력이 필요하므로 내부 수집 공백일은
    선형 보간해 넘기고, 분해 후 해당 날짜는 다시 결측으로 되돌려
    없는 데이터를 지어내지 않는다.
    """
    col_series = df_raw[col]
    first = col_series.first_valid_index()
    last = col_series.last_valid_index()
    if first is None or col_series.loc[first:last].count() < 14:
        df_deseason[col] = col_series
        return

    segment = col_series.loc[first:last]
    gap_mask = segment.isna()
    filled = segment.interpolate(method="linear")
    decomposed = _stl_decompose(filled, period=7).mask(gap_mask)

    df_deseason[col] = col_series.copy()
    df_deseason.loc[segment.index, col] = decomposed


def _apply_stl_decompose(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Phase B: STL 분해 (요일 효과 제거)."""
    logger.info("활동지수 Phase B: STL 분해 적용")
    df_deseason = pd.DataFrame(index=df_raw.index)

    for col in df_raw.columns:
        _apply_stl_to_column(df_raw, df_deseason, col)

    return df_deseason


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


def _detect_outliers(normalized: pd.DataFrame) -> dict:
    """Phase C: MAD 이상치 감지."""
    logger.info("활동지수 Phase C: MAD 이상치 감지")
    outliers = {}
    for date_idx in normalized.index:
        row = normalized.loc[date_idx]
        outlier_items = _mad_outlier_detection(row, threshold=3.0)
        if outlier_items:
            date_str = date_idx.strftime("%Y-%m-%d")
            outliers[date_str] = outlier_items
    return outliers


# ───────────────────────────────────────────
# Phase D: PELT 변화점 탐지 (표시 주석 전용)
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


def _run_changepoint_detection(normalized: pd.DataFrame) -> list:
    """
    Phase D: PELT 변화점 탐지.

    아이템 간 스케일 차이·수집 시작 시점 차이로 인한 허위 변화점을
    막기 위해 정규화된 값의 중앙값 시계열에 대해 탐지한다.
    결과는 기준선 재설정에 쓰지 않고 차트/embed 표시에만 사용한다.
    """
    logger.info("활동지수 Phase D: PELT 변화점 탐지")
    temp_median = normalized.median(axis=1).dropna()
    changepoint_dates = _detect_changepoints(
        temp_median, min_size=14, penalty=5.0
    )
    if changepoint_dates:
        cp_str = [d.strftime("%Y-%m-%d") for d in changepoint_dates]
        logger.info(f"변화점 감지: {cp_str}")
    return changepoint_dates


# ───────────────────────────────────────────
# 파이프라인 단계별 헬퍼 함수
# ───────────────────────────────────────────

async def _load_series_data(basket: list, fetch_days: int) -> dict:
    """1단계: 바스켓 아이템의 일별 거래량 수집 (KST 기준, 당일 제외)."""
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
    return all_series


def _build_raw_dataframe(all_series: dict, watched_names: set) -> pd.DataFrame:
    """
    수집된 시리즈를 달력 기준 일 단위 데이터프레임으로 구성.

    무거래일 처리 원칙:
    - 수집 가동일(어느 아이템이든 관측이 있는 날)에 특정 아이템만
      거래가 없으면 실제 무거래이므로 0으로 채운다.
    - 전 아이템이 비어 있는 날은 봇 다운타임 등 수집 공백과
      구분할 수 없으므로 0으로 단정하지 않고 결측으로 남긴다.
    - 시세 감시가 해제된 아이템(watched_names 밖)은 마지막 관측일
      이후 수집이 멈춘 것이므로 그 뒤를 0으로 채우지 않는다.
    - 수집 시작 이전 구간은 미추적이므로 결측 유지.
    """
    start = min(s.index.min() for s in all_series.values())
    end = max(s.index.max() for s in all_series.values())
    full_range = pd.date_range(start, end, freq="D")

    collection_dates = pd.DatetimeIndex(
        sorted(set().union(*(s.index for s in all_series.values())))
    )

    df_raw = pd.DataFrame(index=full_range)
    for name, series in all_series.items():
        col = series.reindex(full_range)
        fill_mask = (
            full_range.isin(collection_dates)
            & (full_range >= series.index.min())
        )
        if name not in watched_names:
            fill_mask &= (full_range <= series.index.max())
        col.loc[fill_mask] = col.loc[fill_mask].fillna(0.0)
        df_raw[name] = col
    return df_raw


def _normalize_anchored(df: pd.DataFrame) -> pd.DataFrame:
    """
    앵커 정규화: 각 아이템을 구간 평균 대비 비율(%)로 변환.

    기준선이 데이터를 따라 움직이는 이동평균 방식과 달리
    구간 평균을 고정 기준(100%)으로 삼으므로, 지속적인 활동
    증감이 평균회귀로 사라지지 않고 지수 수준(level)에 남는다.

    한계: 기준선은 해당 아이템의 관측 가능 구간 평균이므로,
    수집 이력이 짧은 신규 아이템은 최근 체제만이 기준이 된다.
    (MIN_OBSERVATIONS 미만 아이템은 제외로 완화)
    """
    normalized = pd.DataFrame(index=df.index)
    for col in df.columns:
        col_data = df[col].dropna()
        if len(col_data) < MIN_OBSERVATIONS:
            continue
        baseline = col_data.mean()
        if baseline <= 0:
            continue
        normalized[col] = col_data / baseline * 100
    return normalized


def _build_raw_values(raw_daily_median: pd.Series, daily_median: pd.Series) -> list:
    """원본 지수 값 리스트 생성 (산출 불가 구간은 NaN 유지 → 차트에서 선이 끊김)."""
    raw_reindexed = raw_daily_median.reindex(daily_median.index)
    return [
        round(v, 1) if not np.isnan(v) else float("nan")
        for v in raw_reindexed.values
    ]


def _filter_changepoints_for_display(changepoint_dates: list, daily_median: pd.Series) -> list[str]:
    """표시 기간에 해당하는 변화점만 필터링."""
    if not len(daily_median.index):
        return []
    return [
        d.strftime("%Y-%m-%d") for d in changepoint_dates
        if d >= daily_median.index[0]
    ]


def _assemble_result(
    daily_median: pd.Series,
    raw_daily_median: pd.Series,
    item_count: int,
    outliers: dict,
    changepoint_dates: list,
    spike_stats: dict,
    baseline_days: int,
) -> dict:
    """최종 결과 딕셔너리 조립."""
    dates = [d.strftime("%Y-%m-%d") for d in daily_median.index]
    index_values = [round(v, 1) for v in daily_median.values]
    raw_values = _build_raw_values(raw_daily_median, daily_median)
    cp_strs = _filter_changepoints_for_display(changepoint_dates, daily_median)

    logger.info(
        f"활동지수 산출 완료: {len(dates)}일, "
        f"이상치 {len(outliers)}건, 변화점 {len(cp_strs)}건"
    )

    return {
        "dates": dates,
        "index": index_values,
        "raw_index": raw_values,
        "item_count": item_count,
        "baseline_days": baseline_days,
        "outliers": outliers,
        "changepoints": cp_strs,
        "spike_stats": spike_stats,
    }


# ───────────────────────────────────────────
# 메인 파이프라인
# ───────────────────────────────────────────

async def calc_activity_index(display_days: int = 30) -> dict | None:
    """
    활동 수준(level) 지수 산출.

    일별 거래량은 KST 달력 기준으로 집계하며 진행 중인 오늘은 제외.
    수집 가동일의 무거래는 0으로, 전 아이템 공백일(다운타임 등)은
    결측으로 처리한다. 기준선은 최근 BASELINE_DAYS일 평균으로
    고정되어 조회 옵션(days)과 무관하게 같은 날짜는 같은 값이 된다.

    파이프라인:
        A) Hampel 스파이크 감지 → 이벤트성 급변 플래그 (치환 없음)
        B) STL 분해 → 요일 주기성 제거
        -) 앵커 정규화 → 기준선 기간 평균 = 100% 기준 수준 지수
        C) MAD 이상치 감지 → 아이템 간 이상 급변 플래그
        D) PELT 변화점 탐지 → 체제 전환 표시 (주석 전용)

    Returns:
        {
            "dates": [str, ...],
            "index": [float, ...],          # 활동지수 (요일 보정)
            "raw_index": [float, ...],      # 요일 보정 전 원본 지수
            "item_count": int,              # 표시 구간에 실제 참여한 아이템 수
            "baseline_days": int,           # 100% 기준선의 실제 데이터 스팬(일)
            "outliers": {date: [item_name, ...]},
            "changepoints": [date_str, ...],
            "spike_stats": {
                "total_flagged": int,
                "items": {name: count}
            },
        }
        또는 데이터 부족 시 None
    """
    basket = await get_basket_items()
    if len(basket) < MIN_BASKET_ITEMS:
        return None

    fetch_days = max(display_days, BASELINE_DAYS)

    # ── 1단계: 일별 거래량 수집 ──
    all_series = await _load_series_data(basket, fetch_days)
    if len(all_series) < MIN_BASKET_ITEMS:
        return None

    # 시세 감시가 살아있는 아이템만 최신 구간 0채움 대상
    watch_items = await get_all_watch_items()
    watched_ids = {w["item_id"] for w in watch_items}
    watched_names = {
        b["item_name"] for b in basket if b["item_id"] in watched_ids
    }

    df_raw = _build_raw_dataframe(all_series, watched_names)

    # ── Phase A: 스파이크 플래그 (지수에는 그대로 반영) ──
    spike_stats = _detect_spikes(df_raw)

    # ── Phase B: 요일 효과 제거 ──
    df_deseason = _apply_stl_decompose(df_raw)

    # ── 앵커 정규화 (기준선 기간 평균 = 100%) ──
    normalized = _normalize_anchored(df_deseason)
    raw_normalized = _normalize_anchored(df_raw)
    if normalized.empty:
        return None

    # ── Phase D: 변화점 탐지 (표시 주석 전용) ──
    changepoint_dates = _run_changepoint_detection(normalized)

    # 표시 기간만 잘라내기 (달력 일 단위 인덱스)
    normalized_display = normalized.iloc[-display_days:].dropna(how="all")
    raw_display = raw_normalized.iloc[-display_days:]

    if normalized_display.empty:
        return None

    # 표시 구간에 실제 값이 있는 아이템만 참여 수로 집계
    item_count = len(normalized_display.dropna(axis=1, how="all").columns)
    if item_count < MIN_BASKET_ITEMS:
        return None

    # ── 일별 중앙값 = 활동지수 ──
    daily_median = normalized_display.median(axis=1)
    raw_daily_median = raw_display.median(axis=1)

    # ── Phase C: MAD 이상치 감지 ──
    outliers = _detect_outliers(normalized_display)

    # 결과 조립
    return _assemble_result(
        daily_median, raw_daily_median, item_count,
        outliers, changepoint_dates, spike_stats,
        baseline_days=min(BASELINE_DAYS, len(df_raw.index)),
    )
