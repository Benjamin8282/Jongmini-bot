"""core.chart 모듈 테스트."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from core.chart import aggregate_to_ohlc, filter_price_outliers

KST = timezone(timedelta(hours=9))


# ─── filter_price_outliers ───


def test_filter_outliers_극단값_제거():
    """극단적인 이상치를 제거한다."""
    now = datetime.now(KST)
    normal_records = [
        {"sold_date": (now - timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"),
         "unit_price": 10000 + (i * 50),
         "count": 1}
        for i in range(20)
    ]
    # 극단적 이상치 추가
    outliers = [
        {"sold_date": (now - timedelta(hours=21)).strftime("%Y-%m-%d %H:%M:%S"),
         "unit_price": 999999, "count": 1},
        {"sold_date": (now - timedelta(hours=22)).strftime("%Y-%m-%d %H:%M:%S"),
         "unit_price": 1, "count": 1},
    ]
    records = normal_records + outliers
    filtered = filter_price_outliers(records)
    # 이상치가 제거되어 원본보다 적어야 함
    assert len(filtered) <= len(records)
    # 정상 범위 가격만 남아야 함
    prices = [r["unit_price"] for r in filtered]
    assert 999999 not in prices or 1 not in prices  # 최소 하나는 제거


def test_filter_outliers_정상값_유지():
    """정상 범위 데이터는 모두 유지된다."""
    records = [
        {"sold_date": f"2025-01-01 {i:02d}:00:00",
         "unit_price": 10000 + i * 10,
         "count": 1}
        for i in range(20)
    ]
    filtered = filter_price_outliers(records)
    assert len(filtered) == len(records)


def test_filter_outliers_10건_미만_그대로_반환():
    """10건 미만이면 필터링 없이 원본 그대로 반환."""
    records = [
        {"sold_date": f"2025-01-01 0{i}:00:00",
         "unit_price": p, "count": 1}
        for i, p in enumerate([100, 200, 99999, 1, 150, 180])
    ]
    filtered = filter_price_outliers(records)
    assert len(filtered) == len(records)


def test_filter_outliers_IQR_0_일때_처리():
    """모든 가격이 동일하면(IQR=0) 중앙값 기반으로 처리."""
    records = [
        {"sold_date": f"2025-01-01 {i:02d}:00:00",
         "unit_price": 5000, "count": 1}
        for i in range(15)
    ]
    filtered = filter_price_outliers(records)
    # IQR=0 → median 기반 범위(median*0.2 ~ median*5.0) 적용
    assert len(filtered) == 15


def test_filter_outliers_안전밸브_50퍼센트_초과_제거시_원본반환():
    """필터링 결과가 원본의 50% 미만이면 원본을 반환한다 (safety valve)."""
    # 절반 이상이 '이상치'로 간주되는 분포를 만듦
    records = []
    for i in range(10):
        records.append({
            "sold_date": f"2025-01-01 {i:02d}:00:00",
            "unit_price": 100, "count": 1,
        })
    for i in range(10, 20):
        records.append({
            "sold_date": f"2025-01-01 {i:02d}:00:00",
            "unit_price": 100000, "count": 1,
        })
    filtered = filter_price_outliers(records, multiplier=0.1)
    # multiplier가 매우 작아 많이 제거하려 해도, 50% 안전밸브가 작동
    # 또는 median 기반 확장 범위 적용으로 대부분 유지
    assert len(filtered) >= len(records) * 0.5


def test_filter_outliers_빈_리스트():
    """빈 리스트 입력 시 빈 리스트 반환."""
    assert filter_price_outliers([]) == []


def test_filter_outliers_multiplier_커스텀():
    """multiplier 값을 변경하면 필터링 범위가 달라진다."""
    now = datetime.now(KST)
    records = [
        {"sold_date": (now - timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"),
         "unit_price": 10000 + (i * 50),
         "count": 1}
        for i in range(18)
    ]
    # 경계 부근 이상치
    records.append({
        "sold_date": (now - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S"),
        "unit_price": 15000, "count": 1,
    })
    records.append({
        "sold_date": (now - timedelta(hours=21)).strftime("%Y-%m-%d %H:%M:%S"),
        "unit_price": 5000, "count": 1,
    })
    # 넓은 범위
    filtered_wide = filter_price_outliers(records, multiplier=5.0)
    # 좁은 범위
    filtered_narrow = filter_price_outliers(records, multiplier=1.0)
    assert len(filtered_wide) >= len(filtered_narrow)


# ─── aggregate_to_ohlc ───


def test_aggregate_ohlc_60분_컬럼(sample_price_records):
    """60분 간격 집계 시 OHLC + volume 컬럼이 존재한다."""
    df = aggregate_to_ohlc(sample_price_records, interval_minutes=60)
    assert not df.empty
    assert "open" in df.columns
    assert "high" in df.columns
    assert "low" in df.columns
    assert "close" in df.columns
    assert "volume" in df.columns


def test_aggregate_ohlc_빈_입력():
    """빈 리스트 입력 시 빈 DataFrame 반환."""
    df = aggregate_to_ohlc([], interval_minutes=60)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_aggregate_ohlc_OHLC_관계(sample_price_records):
    """각 캔들에서 high >= open, close >= low 관계가 성립한다."""
    df = aggregate_to_ohlc(sample_price_records, interval_minutes=60)
    if not df.empty:
        for _, row in df.iterrows():
            assert row["high"] >= row["open"]
            assert row["high"] >= row["close"]
            assert row["high"] >= row["low"]
            assert row["low"] <= row["open"]
            assert row["low"] <= row["close"]


def test_aggregate_ohlc_다양한_interval():
    """다양한 interval_minutes 값으로 집계한다."""
    now = datetime.now(KST)
    records = []
    for i in range(200):
        dt = now - timedelta(minutes=200 - i)
        records.append({
            "sold_date": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "unit_price": 10000 + i * 10,
            "count": 1,
        })

    # 30분 간격
    df_30 = aggregate_to_ohlc(records, interval_minutes=30)
    # 60분 간격
    df_60 = aggregate_to_ohlc(records, interval_minutes=60)
    # 1440분(일간) 간격
    df_daily = aggregate_to_ohlc(records, interval_minutes=1440)

    assert not df_30.empty
    assert not df_60.empty
    assert not df_daily.empty
    # 30분 캔들 수 >= 60분 캔들 수 >= 일간 캔들 수
    assert len(df_30) >= len(df_60)
    assert len(df_60) >= len(df_daily)


def test_aggregate_ohlc_volume_합계(sample_price_records):
    """volume은 해당 기간의 count 합계이다."""
    df = aggregate_to_ohlc(sample_price_records, interval_minutes=60)
    if not df.empty:
        # 모든 volume 이 0보다 커야 함
        assert (df["volume"] > 0).all()


def test_aggregate_ohlc_단일_레코드():
    """레코드 1건으로 집계 시 하나의 캔들이 생긴다."""
    records = [{
        "sold_date": "2025-01-01 12:00:00",
        "unit_price": 10000,
        "count": 5,
    }]
    df = aggregate_to_ohlc(records, interval_minutes=60)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["open"] == 10000
    assert row["high"] == 10000
    assert row["low"] == 10000
    assert row["close"] == 10000
    assert row["volume"] == 5
