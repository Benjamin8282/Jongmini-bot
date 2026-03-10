import pandas as pd

from core.db import get_basket_items, get_daily_avg_prices

BASE_VALUE = 1000.0  # 기준일 지수 = 1000


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
    basket = await get_basket_items()
    if len(basket) < 2:
        return None

    fetch_days = display_days + 30  # 기준일 확보 여유분

    # 각 아이템의 일별 평균가 수집
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

    if len(all_series) < 2:
        return None

    # 전체 날짜 범위 통합
    all_dates = sorted(
        set().union(*(s.index for s in all_series.values()))
    )
    df = pd.DataFrame(index=all_dates)
    for name, series in all_series.items():
        df[name] = series
    df = df.sort_index().ffill()

    # 기준일: 모든 아이템 데이터가 있는 가장 이른 날
    valid_mask = df.notna().all(axis=1)
    valid_dates = df.index[valid_mask]
    if len(valid_dates) < 5:
        return None

    base_date = valid_dates[0]
    base_prices = df.loc[base_date]

    # 각 아이템을 기준일 대비 비율로 정규화 후 동일 가중 평균
    normalized = df.div(base_prices) * BASE_VALUE
    index_series = normalized.mean(axis=1)

    # 표시 기간
    index_series = index_series.iloc[-display_days:]
    index_series = index_series.dropna()

    if index_series.empty:
        return None

    current = index_series.iloc[-1]
    prev_close = index_series.iloc[-2] if len(index_series) >= 2 else current
    change = current - prev_close
    change_pct = (change / prev_close * 100) if prev_close != 0 else 0

    # 종목별 기여도
    components = []
    for name in df.columns:
        col = df[name].dropna()
        if len(col) < 2:
            continue
        latest = col.iloc[-1]
        prev = col.iloc[-2] if len(col) >= 2 else latest
        pct = (latest - prev) / prev * 100 if prev != 0 else 0
        components.append({
            "name": name,
            "price": latest,
            "change_pct": round(pct, 2),
        })

    components.sort(key=lambda x: x["change_pct"], reverse=True)

    dates = [d.strftime("%Y-%m-%d") for d in index_series.index]
    values = [round(v, 2) for v in index_series.values]

    return {
        "dates": dates,
        "index": values,
        "current": round(current, 2),
        "prev_close": round(prev_close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "high": round(max(values), 2),
        "low": round(min(values), 2),
        "item_count": len(all_series),
        "base_date": base_date.strftime("%Y-%m-%d"),
        "components": components,
    }
