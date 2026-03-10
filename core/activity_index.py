import pandas as pd
import numpy as np

from core.db import get_basket_items, get_daily_volumes
from core.logger import logger


async def calc_activity_index(display_days: int = 30) -> dict | None:
    """
    바스켓 아이템들의 일별 거래량을 정규화하고 중앙값으로 활동지수 산출.

    Returns:
        {
            "dates": [str, ...],
            "index": [float, ...],         # 100 = 30일 평균 수준
            "item_count": int,             # 바스켓 아이템 수
            "outliers": {date: [item_name, ...]},  # 이상치 아이템
        }
        또는 데이터 부족 시 None
    """
    basket = await get_basket_items()
    if len(basket) < 3:
        return None

    # 30일 이동평균 계산을 위해 추가 기간 확보
    fetch_days = display_days + 45

    # 각 아이템의 일별 거래량 수집
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
    all_dates = sorted(set().union(*(s.index for s in all_series.values())))
    df = pd.DataFrame(index=all_dates)
    for name, series in all_series.items():
        df[name] = series

    df = df.sort_index()

    # 각 아이템을 자기 자신의 30일 이동평균 대비 비율(%)로 정규화
    normalized = pd.DataFrame(index=df.index)
    for col in df.columns:
        ma30 = df[col].rolling(window=30, min_periods=15).mean()
        normalized[col] = df[col] / ma30 * 100

    # 표시 기간만 잘라내기
    normalized = normalized.iloc[-display_days:]
    normalized = normalized.dropna(how="all")

    if normalized.empty:
        return None

    # 일별 중앙값 = 활동지수
    daily_median = normalized.median(axis=1)

    # 이상치 감지: 중앙값에서 2σ 이상 벗어난 아이템
    outliers = {}
    for date_idx in normalized.index:
        row = normalized.loc[date_idx].dropna()
        if len(row) < 3:
            continue
        med = row.median()
        std = row.std()
        if std == 0:
            continue
        for item_name, val in row.items():
            if abs(val - med) > 2 * std:
                date_str = date_idx.strftime("%Y-%m-%d")
                outliers.setdefault(date_str, []).append(
                    f"{item_name} ({val:.0f}%)"
                )

    dates = [d.strftime("%Y-%m-%d") for d in daily_median.index]
    index_values = [round(v, 1) for v in daily_median.values]

    return {
        "dates": dates,
        "index": index_values,
        "item_count": len(all_series),
        "outliers": outliers,
    }
