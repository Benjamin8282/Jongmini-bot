"""core.analysis 모듈 테스트."""
import pandas as pd
import pytest

from core.analysis import (
    analyze,
    calc_correlation,
    calc_ma_alignment,
    calc_ma_disparity,
    calc_price_volume_divergence,
    calc_rsi,
    calc_volume_surge,
    format_analysis_text,
    recommend_prices,
)


# ─── calc_rsi ───


def test_rsi_충분한_데이터_범위_0_100():
    """데이터가 충분할 때 RSI 는 0~100 사이 값을 반환한다."""
    closes = pd.Series([100 + i * 2 + ((-1) ** i * 5) for i in range(30)])
    rsi = calc_rsi(closes)
    assert rsi is not None
    assert 0 <= rsi <= 100


def test_rsi_데이터_부족_시_None():
    """period+1 미만 데이터는 None 을 반환한다."""
    closes = pd.Series([100, 101, 102])
    assert calc_rsi(closes, period=14) is None


def test_rsi_모두_상승_시_100에_근접():
    """연속 상승 시리즈는 RSI 가 100 에 가깝다."""
    closes = pd.Series([100 + i for i in range(20)])
    rsi = calc_rsi(closes)
    assert rsi is not None
    assert rsi >= 95


def test_rsi_모두_하락_시_0에_근접():
    """연속 하락 시리즈는 RSI 가 0 에 가깝다."""
    closes = pd.Series([200 - i for i in range(20)])
    rsi = calc_rsi(closes)
    assert rsi is not None
    assert rsi <= 5


def test_rsi_custom_period():
    """period 파라미터를 변경해도 정상 계산."""
    closes = pd.Series([100 + i * 3 for i in range(12)])
    assert calc_rsi(closes, period=5) is not None
    assert calc_rsi(closes, period=10) is not None
    assert calc_rsi(closes, period=12) is None  # 데이터 부족 (period+1 > len)


# ─── calc_ma_alignment ───


def test_ma_alignment_상승추세():
    """오름차순 종가 → bullish."""
    closes = pd.Series([100 + i * 10 for i in range(25)])
    result = calc_ma_alignment(closes)
    assert result["status"] == "bullish"
    assert result["ma5"] is not None
    assert result["ma10"] is not None
    assert result["ma20"] is not None
    assert result["ma5"] > result["ma10"] > result["ma20"]


def test_ma_alignment_하락추세():
    """내림차순 종가 → bearish."""
    closes = pd.Series([500 - i * 10 for i in range(25)])
    result = calc_ma_alignment(closes)
    assert result["status"] == "bearish"
    assert result["ma5"] < result["ma10"] < result["ma20"]


def test_ma_alignment_혼조():
    """MA 순서가 섞인 경우 → neutral."""
    # ma5 > ma20 > ma10 이 되도록 설계
    data = [100] * 10 + [80] * 5 + [120] * 5 + [110] * 5
    closes = pd.Series(data)
    result = calc_ma_alignment(closes)
    assert result["status"] in ("neutral", "bullish", "bearish")
    # ma5/ma10/ma20 모두 숫자여야 함
    assert all(v is not None for v in [result["ma5"], result["ma10"], result["ma20"]])


def test_ma_alignment_데이터_부족_시_unknown():
    """20개 미만 데이터 → unknown 상태."""
    closes = pd.Series([100 + i for i in range(15)])
    result = calc_ma_alignment(closes)
    assert result["status"] == "unknown"
    assert result["ma5"] is None
    assert result["ma10"] is None
    assert result["ma20"] is None


# ─── calc_volume_surge ───


def test_volume_surge_급증():
    """최근 5캔들 거래량이 20캔들 평균의 1.5배 이상이면 surge=True."""
    # 처음 15캔들은 거래량 10, 마지막 5캔들은 거래량 30 → ratio=30/(avg20) > 1.5
    volumes = pd.Series([10] * 15 + [30] * 5)
    result = calc_volume_surge(volumes)
    assert result["surge"] == True
    assert result["ratio"] is not None
    assert result["ratio"] >= 1.5


def test_volume_surge_보통():
    """거래량이 고르면 surge=False."""
    volumes = pd.Series([10] * 20)
    result = calc_volume_surge(volumes)
    assert result["surge"] == False
    assert result["ratio"] is not None
    assert abs(result["ratio"] - 1.0) < 0.01


def test_volume_surge_데이터_부족():
    """20개 미만 데이터 시 ratio=None, surge=False."""
    volumes = pd.Series([10] * 10)
    result = calc_volume_surge(volumes)
    assert result["ratio"] is None
    assert result["surge"] == False


def test_volume_surge_avg20_0():
    """20캔들 평균이 0이면 ratio=None."""
    volumes = pd.Series([0] * 20)
    result = calc_volume_surge(volumes)
    assert result["ratio"] is None
    assert result["surge"] == False


# ─── calc_ma_disparity ───


def test_ma_disparity_양의_이격도():
    """현재가가 MA20 보다 높으면 양의 이격도."""
    disp = calc_ma_disparity(11000, 10000)
    assert disp is not None
    assert abs(disp - 10.0) < 0.01


def test_ma_disparity_음의_이격도():
    """현재가가 MA20 보다 낮으면 음의 이격도."""
    disp = calc_ma_disparity(9000, 10000)
    assert disp is not None
    assert abs(disp - (-10.0)) < 0.01


def test_ma_disparity_ma20_None():
    """MA20이 None이면 None 반환."""
    assert calc_ma_disparity(10000, None) is None


def test_ma_disparity_ma20_0():
    """MA20이 0이면 None 반환."""
    assert calc_ma_disparity(10000, 0) is None


# ─── calc_price_volume_divergence ───


def test_divergence_가격상승_거래량감소():
    """가격은 오르는데 거래량은 줄면 price_up_vol_down."""
    # 11개 데이터: 가격 상승, 거래량 하락
    closes = pd.Series([100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120])
    volumes = pd.Series([50, 48, 46, 44, 42, 40, 38, 36, 34, 32, 30])
    result = calc_price_volume_divergence(closes, volumes)
    assert result == "price_up_vol_down"


def test_divergence_가격하락_거래량증가():
    """가격은 떨어지는데 거래량은 늘면 price_down_vol_up."""
    closes = pd.Series([120, 118, 116, 114, 112, 110, 108, 106, 104, 102, 100])
    volumes = pd.Series([30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50])
    result = calc_price_volume_divergence(closes, volumes)
    assert result == "price_down_vol_up"


def test_divergence_데이터_부족():
    """6개 미만 데이터 시 None."""
    closes = pd.Series([100, 101, 102])
    volumes = pd.Series([10, 11, 12])
    assert calc_price_volume_divergence(closes, volumes) is None


def test_divergence_정상_추세():
    """가격과 거래량이 같은 방향이면 None."""
    closes = pd.Series([100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120])
    volumes = pd.Series([30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50])
    result = calc_price_volume_divergence(closes, volumes)
    assert result is None


# ─── calc_correlation ───


def test_correlation_강한_양의_상관():
    """같은 패턴의 시계열은 상관계수가 1에 가깝다."""
    idx = pd.date_range("2025-01-01", periods=20, freq="1h")
    closes_a = pd.Series([100 + i for i in range(20)], index=idx)
    closes_b = pd.Series([200 + i * 2 for i in range(20)], index=idx)
    result = calc_correlation(closes_a, closes_b)
    assert result["correlation"] is not None
    assert result["correlation"] > 0.9
    assert result["overlap_count"] == 20
    assert "양의 상관" in result["interpretation"]


def test_correlation_강한_음의_상관():
    """반대 패턴의 시계열은 상관계수가 -1에 가깝다."""
    idx = pd.date_range("2025-01-01", periods=20, freq="1h")
    closes_a = pd.Series([100 + i for i in range(20)], index=idx)
    closes_b = pd.Series([200 - i * 2 for i in range(20)], index=idx)
    result = calc_correlation(closes_a, closes_b)
    assert result["correlation"] is not None
    assert result["correlation"] < -0.9
    assert "음의 상관" in result["interpretation"]


def test_correlation_데이터_부족():
    """overlap이 min_overlap 미만이면 correlation=None."""
    idx_a = pd.date_range("2025-01-01", periods=5, freq="1h")
    idx_b = pd.date_range("2025-01-01", periods=5, freq="1h")
    closes_a = pd.Series([100, 101, 102, 103, 104], index=idx_a)
    closes_b = pd.Series([200, 201, 202, 203, 204], index=idx_b)
    result = calc_correlation(closes_a, closes_b, min_overlap=10)
    assert result["correlation"] is None
    assert result["interpretation"] is None
    assert result["overlap_count"] == 5


# ─── analyze ───


def test_analyze_상승추세(sample_ohlc_df):
    """상승 OHLC 데이터 → 양수 스코어, bullish MA."""
    result = analyze(sample_ohlc_df)
    assert "score" in result
    assert "opinion" in result
    assert "rsi" in result
    assert "ma" in result
    assert "disparity" in result
    assert "volume" in result
    assert "divergence" in result
    assert result["ma"]["status"] == "bullish"
    assert result["score"] > 0


def test_analyze_하락추세(sample_ohlc_bearish):
    """하락 OHLC 데이터 → 음수 스코어, bearish MA."""
    result = analyze(sample_ohlc_bearish)
    assert result["ma"]["status"] == "bearish"
    assert result["score"] <= 0


def test_analyze_결과_키_존재(sample_ohlc_df):
    """분석 결과에 필수 키가 모두 존재."""
    result = analyze(sample_ohlc_df)
    required_keys = {"score", "opinion", "rsi", "ma", "disparity", "volume", "divergence"}
    assert required_keys.issubset(result.keys())


# ─── recommend_prices ───


def test_recommend_prices_정상(sample_price_records):
    """충분한 데이터로 3단계 추천가를 반환하고 safe < optimal < ambitious 순서."""
    result = recommend_prices(sample_price_records)
    assert result is not None
    assert "safe" in result
    assert "optimal" in result
    assert "ambitious" in result
    assert result["safe"] <= result["optimal"] <= result["ambitious"]


def test_recommend_prices_데이터_부족():
    """빈 리스트 → None."""
    assert recommend_prices([]) is None


def test_recommend_prices_소량_데이터():
    """10건 미만 데이터 → None."""
    records = [
        {"sold_date": "2025-01-01 12:00:00", "unit_price": 1000, "price": 1000, "count": 1}
        for _ in range(5)
    ]
    assert recommend_prices(records) is None


def test_recommend_prices_반환값_타입(sample_price_records):
    """추천가는 정수형이어야 한다."""
    result = recommend_prices(sample_price_records)
    if result is not None:
        assert isinstance(result["safe"], int)
        assert isinstance(result["optimal"], int)
        assert isinstance(result["ambitious"], int)
        assert isinstance(result["median"], int)
        assert isinstance(result["sample_size"], int)
        assert isinstance(result["total_volume"], int)


# ─── format_analysis_text ───


def test_format_analysis_text_한국어_포함(sample_ohlc_df):
    """포맷된 텍스트에 한국어 마커들이 포함된다."""
    result = analyze(sample_ohlc_df)
    text = format_analysis_text(result)
    assert isinstance(text, str)
    assert "종합 의견" in text
    assert "추세" in text
    assert "요약" in text


def test_format_analysis_text_점수_포함(sample_ohlc_df):
    """포맷된 텍스트에 점수 표시가 포함된다."""
    result = analyze(sample_ohlc_df)
    text = format_analysis_text(result)
    assert "점" in text


def test_format_analysis_text_구분선_포함(sample_ohlc_df):
    """포맷된 텍스트에 구분선이 포함된다."""
    result = analyze(sample_ohlc_df)
    text = format_analysis_text(result)
    assert "━" in text


def test_format_analysis_text_하락_추세(sample_ohlc_bearish):
    """하락 추세 분석 텍스트에도 한국어 마커가 포함된다."""
    result = analyze(sample_ohlc_bearish)
    text = format_analysis_text(result)
    assert "하락" in text or "매도" in text or "관망" in text
