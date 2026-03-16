import pandas as pd

from core.db import get_basket_items, get_daily_avg_prices

BASE_VALUE = 1000.0  # 기준일 지수 = 1000


async def _collect_price_series(basket: list, fetch_days: int) -> dict:
    """각 아이템의 일별 평균가 수집."""
    all_series = {}
    for item in basket:
        rows = await get_daily_avg_prices(item["item_id"], fetch_days)
        if not rows:
            continue
        series = pd.Series(
            {r["date"]: r["avg_price"] for r in rows},
            dtype=float,
        )
        series.index = pd.to_datetime(series.index)
        all_series[item["item_name"]] = series
    return all_series


def _build_price_dataframe(all_series: dict) -> pd.DataFrame:
    """수집된 시리즈를 통합 데이터프레임으로 구성하고 ffill 적용."""
    all_dates = sorted(
        set().union(*(s.index for s in all_series.values()))
    )
    df = pd.DataFrame(index=all_dates)
    for name, series in all_series.items():
        df[name] = series
    return df.sort_index().ffill()


def _find_base_date(df: pd.DataFrame):
    """기준일: 모든 아이템 데이터가 있는 가장 이른 날. 부족 시 None 반환."""
    valid_mask = df.notna().all(axis=1)
    valid_dates = df.index[valid_mask]
    if len(valid_dates) < 5:
        return None
    return valid_dates[0]


def _compute_index_series(df: pd.DataFrame, base_date, display_days: int):
    """기준일 대비 비율로 정규화 후 동일 가중 평균 산출, 표시 기간 자르기."""
    base_prices = df.loc[base_date]
    normalized = df.div(base_prices) * BASE_VALUE
    index_series = normalized.mean(axis=1)

    index_series = index_series.iloc[-display_days:]
    return index_series.dropna()


def _calc_change_stats(index_series: pd.Series) -> dict:
    """현재값, 전일 종가, 변동폭, 변동률 산출."""
    current = index_series.iloc[-1]
    prev_close = index_series.iloc[-2] if len(index_series) >= 2 else current
    change = current - prev_close
    change_pct = (change / prev_close * 100) if prev_close != 0 else 0
    return {
        "current": round(current, 2),
        "prev_close": round(prev_close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
    }


def _calc_component_change(col: pd.Series) -> dict | None:
    """단일 종목의 전일 대비 변동률 계산."""
    col = col.dropna()
    if len(col) < 2:
        return None
    latest = col.iloc[-1]
    prev = col.iloc[-2]
    pct = (latest - prev) / prev * 100 if prev != 0 else 0
    return {
        "name": col.name,
        "price": latest,
        "change_pct": round(pct, 2),
    }


def _build_components(df: pd.DataFrame) -> list[dict]:
    """종목별 기여도 리스트 생성."""
    components = []
    for name in df.columns:
        comp = _calc_component_change(df[name])
        if comp is not None:
            components.append(comp)
    components.sort(key=lambda x: x["change_pct"], reverse=True)
    return components


async def _prepare_index_data(display_days: int) -> tuple | None:
    """바스켓 데이터 수집 및 인덱스 시리즈 준비. 데이터 부족 시 None."""
    basket = await get_basket_items()
    if len(basket) < 2:
        return None

    fetch_days = display_days + 30  # 기준일 확보 여유분
    all_series = await _collect_price_series(basket, fetch_days)
    if len(all_series) < 2:
        return None

    df = _build_price_dataframe(all_series)
    base_date = _find_base_date(df)
    if base_date is None:
        return None

    index_series = _compute_index_series(df, base_date, display_days)
    if index_series.empty:
        return None

    return all_series, df, base_date, index_series


async def calc_dunspy_index(display_days: int = 30) -> dict | None:
    """
    던스피(DUNSPY) 지수 산출.

    바스켓 아이템들의 가격을 기준일 대비 비율로 정규화한 뒤
    동일 가중 평균으로 합산. 기준일 = 1000.

    Returns:
        {
            "dates": [str, ...],
            "index": [float, ...],
            "current": float,
            "prev_close": float,
            "change": float,
            "change_pct": float,
            "high": float,
            "low": float,
            "item_count": int,
            "components": [
                {"name": str, "change_pct": float, "weight": float},
                ...
            ],
        }
        또는 데이터 부족 시 None
    """
    prepared = await _prepare_index_data(display_days)
    if prepared is None:
        return None

    all_series, df, base_date, index_series = prepared

    stats = _calc_change_stats(index_series)
    components = _build_components(df)

    dates = [d.strftime("%Y-%m-%d") for d in index_series.index]
    values = [round(v, 2) for v in index_series.values]

    return {
        "dates": dates,
        "index": values,
        **stats,
        "high": round(max(values), 2),
        "low": round(min(values), 2),
        "item_count": len(all_series),
        "base_date": base_date.strftime("%Y-%m-%d"),
        "components": components,
    }
