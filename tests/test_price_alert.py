"""tasks/price_alert.py 순수 감지 로직 테스트."""
from datetime import datetime, timedelta

import discord
import pandas as pd
import pytest

from tasks import price_alert
from tasks.price_alert import (
    _is_on_cooldown,
    _set_cooldown,
    _clear_cooldown,
    _try_emit,
    _calc_price_bounds,
    _detect_surge_crash,
    _detect_fat_finger_high,
    _detect_fat_finger_low,
    _detect_new_high,
    _detect_new_low,
    _detect_rsi_signal,
    _detect_ma_cross,
    build_alert_embed,
    KST,
)

# ─── 모듈 상태 초기화 fixture ───


@pytest.fixture(autouse=True)
def clear_alert_state():
    """매 테스트 전후로 모듈 레벨 상태 초기화."""
    price_alert._cooldowns.clear()
    price_alert._prev_state.clear()
    yield
    price_alert._cooldowns.clear()
    price_alert._prev_state.clear()


# ═══════════════════════════════════════════════
# 쿨다운 라이프사이클 테스트
# ═══════════════════════════════════════════════


class TestCooldown:
    """쿨다운 설정/확인/해제 라이프사이클 테스트."""

    def test_not_on_cooldown_initially(self):
        """초기 상태에서는 쿨다운이 아님."""
        assert _is_on_cooldown("item_1", "surge") is False

    def test_set_cooldown_makes_it_active(self):
        """쿨다운 설정 후 활성 상태 확인."""
        _set_cooldown("item_1", "surge")
        assert _is_on_cooldown("item_1", "surge") is True

    def test_cooldown_scoped_by_event_type(self):
        """쿨다운은 (item_id, event_type) 조합으로 분리됨."""
        _set_cooldown("item_1", "surge")
        assert _is_on_cooldown("item_1", "surge") is True
        assert _is_on_cooldown("item_1", "crash") is False
        assert _is_on_cooldown("item_2", "surge") is False

    def test_clear_cooldown(self):
        """쿨다운 해제 후 비활성 상태 확인."""
        _set_cooldown("item_1", "surge")
        assert _is_on_cooldown("item_1", "surge") is True
        _clear_cooldown("item_1", "surge")
        assert _is_on_cooldown("item_1", "surge") is False

    def test_clear_nonexistent_cooldown_no_error(self):
        """존재하지 않는 쿨다운 해제 시 오류 없음."""
        _clear_cooldown("no_such_item", "no_such_event")

    def test_expired_cooldown(self):
        """COOLDOWN_MINUTES 경과 후 쿨다운 만료 확인."""
        key = ("item_1", "surge")
        expired_time = datetime.now(KST) - timedelta(
            minutes=price_alert.COOLDOWN_MINUTES + 1
        )
        price_alert._cooldowns[key] = expired_time
        assert _is_on_cooldown("item_1", "surge") is False


# ═══════════════════════════════════════════════
# _try_emit 테스트
# ═══════════════════════════════════════════════


class TestTryEmit:
    """쿨다운 기반 알림 발행 테스트."""

    def test_emit_returns_data_when_not_on_cooldown(self):
        """쿨다운이 아닐 때 데이터 반환."""
        data = {"type": "surge", "item_name": "테스트검"}
        result = _try_emit("item_1", "surge", data)
        assert result == data

    def test_emit_returns_none_when_on_cooldown(self):
        """쿨다운 중이면 None 반환."""
        data = {"type": "surge", "item_name": "테스트검"}
        _set_cooldown("item_1", "surge")
        result = _try_emit("item_1", "surge", data)
        assert result is None

    def test_emit_sets_cooldown(self):
        """발행 성공 시 쿨다운이 설정됨."""
        data = {"type": "surge", "item_name": "테스트검"}
        _try_emit("item_1", "surge", data)
        assert _is_on_cooldown("item_1", "surge") is True

    def test_emit_clears_specified_types(self):
        """clear_types에 지정된 이벤트의 쿨다운이 해제됨."""
        _set_cooldown("item_1", "crash")
        assert _is_on_cooldown("item_1", "crash") is True

        data = {"type": "surge", "item_name": "테스트검"}
        _try_emit("item_1", "surge", data, clear_types=["crash"])

        # surge가 발행되면서 crash 쿨다운이 해제됨
        assert _is_on_cooldown("item_1", "crash") is False
        assert _is_on_cooldown("item_1", "surge") is True

    def test_emit_clear_types_none(self):
        """clear_types가 None이면 아무것도 해제하지 않음."""
        _set_cooldown("item_1", "crash")
        data = {"type": "surge", "item_name": "테스트검"}
        _try_emit("item_1", "surge", data, clear_types=None)
        assert _is_on_cooldown("item_1", "crash") is True


# ═══════════════════════════════════════════════
# _calc_price_bounds 테스트
# ═══════════════════════════════════════════════


class TestCalcPriceBounds:
    """IQR 기반 이상치 상한선 및 중앙값 계산 테스트."""

    def test_normal_iqr(self):
        """정상 IQR로 upper_bound와 median 계산."""
        prices = list(range(1000, 2001, 100))  # 1000~2000, 11개
        upper, median = _calc_price_bounds(prices)
        assert median == 1500
        # IQR > 0이고 median > 0인 경우: max(q3 + 3*iqr, median*3.0)
        assert upper > median

    def test_iqr_zero_with_positive_median(self):
        """모든 가격이 동일할 때 (IQR=0), median*5.0 반환."""
        prices = [1000] * 20
        upper, median = _calc_price_bounds(prices)
        assert median == 1000
        assert upper == 5000.0  # median * 5.0

    def test_all_zeros(self):
        """모든 가격이 0일 때 upper_bound는 inf."""
        prices = [0] * 20
        upper, median = _calc_price_bounds(prices)
        assert median == 0
        assert upper == float("inf")

    def test_small_spread(self):
        """편차가 작은 가격의 경우."""
        prices = [100, 100, 101, 101, 102, 102, 103, 103, 104, 104]
        upper, median = _calc_price_bounds(prices)
        assert median > 0
        assert upper > median

    def test_wide_spread(self):
        """넓은 범위의 가격 분포."""
        prices = [100, 200, 300, 400, 500, 1000, 2000, 3000, 4000, 5000,
                  6000, 7000, 8000, 9000, 10000]
        upper, median = _calc_price_bounds(prices)
        assert upper > 0
        assert median > 0


# ═══════════════════════════════════════════════
# _detect_surge_crash 테스트
# ═══════════════════════════════════════════════


class TestDetectSurgeCrash:
    """1시간 급등/급락 감지 테스트."""

    def _make_records(self, first_price, last_price, count=5):
        """테스트용 가격 레코드 생성."""
        records = []
        for i in range(count):
            price = first_price + (last_price - first_price) * i // (count - 1)
            records.append({"unit_price": price, "count": 1})
        return records

    def test_surge_detected(self):
        """+30% 이상 상승 → 급등 알림."""
        records = self._make_records(1000, 1400)  # +40%
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "surge"
        assert alerts[0]["level"] == "urgent"

    def test_crash_detected(self):
        """-30% 이하 하락 → 급락 알림."""
        records = self._make_records(1000, 600)  # -40%
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "crash"
        assert alerts[0]["level"] == "urgent"

    def test_small_change_no_alert(self):
        """변동률이 임계값 미만이면 빈 리스트 반환."""
        records = self._make_records(1000, 1100)  # +10%
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert alerts == []

    def test_no_change_no_alert(self):
        """가격 변동 없으면 빈 리스트."""
        records = self._make_records(1000, 1000)
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert alerts == []

    def test_empty_records(self):
        """빈 레코드 → 빈 리스트."""
        alerts = _detect_surge_crash("item_1", "테스트검", [])
        assert alerts == []

    def test_single_record(self):
        """레코드 1개 (len < 2) → 빈 리스트."""
        alerts = _detect_surge_crash("item_1", "테스트검", [{"unit_price": 1000}])
        assert alerts == []

    def test_first_price_zero(self):
        """첫 가격이 0이면 빈 리스트 (ZeroDivisionError 방지)."""
        records = [{"unit_price": 0}, {"unit_price": 1000}]
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert alerts == []

    def test_surge_clears_crash_cooldown(self):
        """급등 감지 시 crash 쿨다운이 해제됨."""
        _set_cooldown("item_1", "crash")
        records = self._make_records(1000, 1400)
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert len(alerts) == 1
        assert _is_on_cooldown("item_1", "crash") is False

    def test_crash_clears_surge_cooldown(self):
        """급락 감지 시 surge 쿨다운이 해제됨."""
        _set_cooldown("item_1", "surge")
        records = self._make_records(1000, 600)
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert len(alerts) == 1
        assert _is_on_cooldown("item_1", "surge") is False

    def test_surge_on_cooldown(self):
        """surge 쿨다운 중이면 알림 안 나감."""
        _set_cooldown("item_1", "surge")
        records = self._make_records(1000, 1400)
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert alerts == []

    def test_exact_boundary_30_percent(self):
        """정확히 +30% → 급등 알림."""
        records = self._make_records(1000, 1300)
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "surge"

    def test_exact_boundary_minus_30_percent(self):
        """정확히 -30% → 급락 알림."""
        records = self._make_records(1000, 700)
        alerts = _detect_surge_crash("item_1", "테스트검", records)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "crash"


# ═══════════════════════════════════════════════
# _detect_fat_finger_high 테스트
# ═══════════════════════════════════════════════


class TestDetectFatFingerHigh:
    """비정상 고가 감지 테스트."""

    def test_price_above_bound(self):
        """현재가가 upper_bound 초과 → 알림 반환."""
        result = _detect_fat_finger_high(
            "item_1", "테스트검",
            current_price=50000, upper_bound=30000, median_price=10000
        )
        assert result is not None
        assert result["type"] == "fat_finger_high"
        assert result["level"] == "fun"
        assert result["overprice"] == 400.0  # (50000/10000 - 1) * 100

    def test_price_at_bound(self):
        """현재가가 upper_bound 이하 → None."""
        result = _detect_fat_finger_high(
            "item_1", "테스트검",
            current_price=30000, upper_bound=30000, median_price=10000
        )
        assert result is None

    def test_price_below_bound(self):
        """현재가가 upper_bound 미만 → None."""
        result = _detect_fat_finger_high(
            "item_1", "테스트검",
            current_price=20000, upper_bound=30000, median_price=10000
        )
        assert result is None

    def test_median_zero(self):
        """중앙값이 0이면 감지하지 않음."""
        result = _detect_fat_finger_high(
            "item_1", "테스트검",
            current_price=50000, upper_bound=30000, median_price=0
        )
        assert result is None


# ═══════════════════════════════════════════════
# _detect_fat_finger_low 테스트
# ═══════════════════════════════════════════════


class TestDetectFatFingerLow:
    """파격세일 (0빼기) 감지 테스트."""

    def test_price_below_60pct_of_median(self):
        """현재가가 중앙값의 60% 미만 → 파격세일 알림."""
        result = _detect_fat_finger_low(
            "item_1", "테스트검",
            current_price=500, median_price=10000
        )
        assert result is not None
        assert result["type"] == "fat_finger"
        assert result["level"] == "fun"
        assert result["discount"] == pytest.approx(95.0)  # (1 - 500/10000)*100

    def test_price_at_60pct_of_median(self):
        """현재가가 중앙값의 60% → None (경계값)."""
        result = _detect_fat_finger_low(
            "item_1", "테스트검",
            current_price=6000, median_price=10000
        )
        assert result is None

    def test_price_above_60pct_of_median(self):
        """현재가가 중앙값의 60% 이상 → None."""
        result = _detect_fat_finger_low(
            "item_1", "테스트검",
            current_price=8000, median_price=10000
        )
        assert result is None

    def test_median_zero(self):
        """중앙값이 0이면 감지하지 않음."""
        result = _detect_fat_finger_low(
            "item_1", "테스트검",
            current_price=100, median_price=0
        )
        assert result is None


# ═══════════════════════════════════════════════
# _detect_new_high / _detect_new_low 테스트
# ═══════════════════════════════════════════════


class TestDetectNewHighLow:
    """신고가/신저가 감지 테스트."""

    def test_new_high_detected(self):
        """과거 최고가를 돌파하면 신고가 알림."""
        past_prices = [1000, 1100, 1200, 1300, 1400]
        result = _detect_new_high(
            "item_1", "테스트검",
            current_price=1500, past_prices=past_prices,
            upper_bound=10000  # 이상치 필터 안 걸리도록 충분히 높게
        )
        assert result is not None
        assert result["type"] == "new_high"
        assert result["price"] == 1500
        assert result["prev_high"] == 1400

    def test_not_new_high(self):
        """과거 최고가 이하면 None."""
        past_prices = [1000, 1100, 1200, 1300, 1500]
        result = _detect_new_high(
            "item_1", "테스트검",
            current_price=1400, past_prices=past_prices,
            upper_bound=10000
        )
        assert result is None

    def test_new_high_filters_outliers(self):
        """upper_bound를 초과하는 이상치를 제외한 최고가 기준."""
        # 이상치(50000)가 포함되어 있지만, upper_bound=30000으로 필터
        past_prices = [1000, 1100, 1200, 50000]
        result = _detect_new_high(
            "item_1", "테스트검",
            current_price=1300, past_prices=past_prices,
            upper_bound=30000
        )
        assert result is not None
        assert result["prev_high"] == 1200  # 50000은 이상치로 제외됨

    def test_new_low_detected(self):
        """과거 최저가 미만이면 신저가 알림."""
        past_prices = [1000, 1100, 1200, 1300, 1400]
        result = _detect_new_low(
            "item_1", "테스트검",
            current_price=900, past_prices=past_prices
        )
        assert result is not None
        assert result["type"] == "new_low"
        assert result["price"] == 900
        assert result["prev_low"] == 1000

    def test_not_new_low(self):
        """과거 최저가 이상이면 None."""
        past_prices = [1000, 1100, 1200]
        result = _detect_new_low(
            "item_1", "테스트검",
            current_price=1000, past_prices=past_prices
        )
        assert result is None


# ═══════════════════════════════════════════════
# _detect_rsi_signal 테스트
# ═══════════════════════════════════════════════


class TestDetectRsiSignal:
    """RSI 과매수/과매도 시그널 감지 테스트."""

    def _make_overbought_closes(self):
        """RSI > 70이 되도록 연속 상승하는 종가 시리즈."""
        # 15개 이상 필요 (period=14 + 1)
        # 급격한 상승: RSI가 70을 넘도록
        prices = [1000 + i * 200 for i in range(20)]
        return pd.Series(prices, dtype=float)

    def _make_oversold_closes(self):
        """RSI < 30이 되도록 연속 하락하는 종가 시리즈."""
        prices = [10000 - i * 200 for i in range(20)]
        return pd.Series(prices, dtype=float)

    def _make_neutral_closes(self):
        """RSI가 30~70 사이인 횡보 종가 시리즈."""
        prices = [1000 + ((-1) ** i) * 10 for i in range(20)]
        return pd.Series(prices, dtype=float)

    def test_overbought_signal(self):
        """RSI > 70 → 과매수 시그널 (neutral → overbought 전환 시)."""
        closes = self._make_overbought_closes()
        alerts = _detect_rsi_signal("item_1", "테스트검", closes)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "rsi_overbought"
        assert alerts[0]["rsi"] > 70

    def test_oversold_signal(self):
        """RSI < 30 → 과매도 시그널."""
        closes = self._make_oversold_closes()
        alerts = _detect_rsi_signal("item_1", "테스트검", closes)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "rsi_oversold"
        assert alerts[0]["rsi"] < 30

    def test_neutral_no_signal(self):
        """RSI가 중립이면 시그널 없음."""
        closes = self._make_neutral_closes()
        alerts = _detect_rsi_signal("item_1", "테스트검", closes)
        assert alerts == []

    def test_same_zone_no_repeat(self):
        """같은 구간이 반복되면 시그널을 재발행하지 않음."""
        closes = self._make_overbought_closes()
        # 첫 번째 호출: 발행
        alerts1 = _detect_rsi_signal("item_1", "테스트검", closes)
        assert len(alerts1) == 1
        # 두 번째 호출: overbought → overbought, 동일 구간이므로 스킵
        alerts2 = _detect_rsi_signal("item_1", "테스트검", closes)
        assert alerts2 == []

    def test_insufficient_data(self):
        """데이터 부족 (14개 미만) → 빈 리스트."""
        closes = pd.Series([1000 + i for i in range(10)], dtype=float)
        alerts = _detect_rsi_signal("item_1", "테스트검", closes)
        assert alerts == []


# ═══════════════════════════════════════════════
# _detect_ma_cross 테스트
# ═══════════════════════════════════════════════


class TestDetectMaCross:
    """골든/데드 크로스 감지 테스트."""

    def test_golden_cross(self):
        """MA5 > MA20으로 교차 → 골든크로스."""
        # 처음에는 하락세(MA5 < MA20), 그 다음에는 상승세(MA5 > MA20)
        # 먼저 하락세로 prev_state 설정
        declining = pd.Series(
            [2000 - i * 50 for i in range(25)], dtype=float
        )
        _detect_ma_cross("item_1", "테스트검", declining)

        # 이제 상승세로 전환
        rising = pd.Series(
            [1000 + i * 100 for i in range(25)], dtype=float
        )
        alerts = _detect_ma_cross("item_1", "테스트검", rising)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "golden_cross"

    def test_dead_cross(self):
        """MA5 < MA20으로 교차 → 데드크로스."""
        # 먼저 상승세로 prev_state 설정
        rising = pd.Series(
            [1000 + i * 100 for i in range(25)], dtype=float
        )
        _detect_ma_cross("item_1", "테스트검", rising)

        # 이제 하락세로 전환
        declining = pd.Series(
            [3000 - i * 50 for i in range(25)], dtype=float
        )
        alerts = _detect_ma_cross("item_1", "테스트검", declining)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "dead_cross"

    def test_no_cross_same_direction(self):
        """방향 변화가 없으면 교차 없음."""
        rising = pd.Series(
            [1000 + i * 100 for i in range(25)], dtype=float
        )
        # 첫 호출: 이전 상태 없으므로 was_above = None → no cross
        alerts1 = _detect_ma_cross("item_1", "테스트검", rising)
        assert alerts1 == []
        # 두 번째: 같은 방향 유지 → no cross
        alerts2 = _detect_ma_cross("item_1", "테스트검", rising)
        assert alerts2 == []

    def test_insufficient_data(self):
        """데이터 부족 (20개 미만) → 빈 리스트."""
        short = pd.Series([1000 + i for i in range(15)], dtype=float)
        alerts = _detect_ma_cross("item_1", "테스트검", short)
        assert alerts == []


# ═══════════════════════════════════════════════
# build_alert_embed 테스트
# ═══════════════════════════════════════════════


class TestBuildAlertEmbed:
    """각 알림 타입에 대한 Embed 생성 테스트."""

    def test_surge_embed(self):
        """surge 알림 → Embed 제목에 '급등' 포함."""
        alert = {
            "type": "surge", "level": "urgent",
            "item_name": "테스트검", "change_pct": 35.5, "price": 13550,
        }
        embed = build_alert_embed(alert)
        assert isinstance(embed, discord.Embed)
        assert "급등" in embed.title
        assert embed.color.value == 0xFF4757

    def test_crash_embed(self):
        """crash 알림 → Embed 제목에 '급락' 포함."""
        alert = {
            "type": "crash", "level": "urgent",
            "item_name": "테스트검", "change_pct": -35.0, "price": 6500,
        }
        embed = build_alert_embed(alert)
        assert isinstance(embed, discord.Embed)
        assert "급락" in embed.title
        assert embed.color.value == 0x3498FF

    def test_new_high_embed(self):
        """new_high 알림 → '신고가' 포함."""
        alert = {
            "type": "new_high", "level": "major",
            "item_name": "테스트검", "price": 15000, "prev_high": 14000,
        }
        embed = build_alert_embed(alert)
        assert "신고가" in embed.title
        assert embed.color.value == 0xFF6348

    def test_new_low_embed(self):
        """new_low 알림 → '신저가' 포함."""
        alert = {
            "type": "new_low", "level": "major",
            "item_name": "테스트검", "price": 8000, "prev_low": 9000,
        }
        embed = build_alert_embed(alert)
        assert "신저가" in embed.title
        assert embed.color.value == 0x3498FF

    def test_volume_spike_embed(self):
        """volume_spike 알림 → '거래 폭증' 포함."""
        alert = {
            "type": "volume_spike", "level": "major",
            "item_name": "테스트검", "vol_1h": 500, "avg_hourly": 20.0,
        }
        embed = build_alert_embed(alert)
        assert "거래 폭증" in embed.title
        assert embed.color.value == 0xFFA502

    def test_golden_cross_embed(self):
        """golden_cross 알림 → '골든크로스' 포함."""
        alert = {
            "type": "golden_cross", "level": "info",
            "item_name": "테스트검",
        }
        embed = build_alert_embed(alert)
        assert "골든크로스" in embed.title

    def test_dead_cross_embed(self):
        """dead_cross 알림 → '데드크로스' 포함."""
        alert = {
            "type": "dead_cross", "level": "info",
            "item_name": "테스트검",
        }
        embed = build_alert_embed(alert)
        assert "데드크로스" in embed.title

    def test_rsi_overbought_embed(self):
        """rsi_overbought 알림 → '과매수' 포함."""
        alert = {
            "type": "rsi_overbought", "level": "info",
            "item_name": "테스트검", "rsi": 75.3,
        }
        embed = build_alert_embed(alert)
        assert "과매수" in embed.title
        assert embed.color.value == 0xFFA502

    def test_rsi_oversold_embed(self):
        """rsi_oversold 알림 → '과매도' 포함."""
        alert = {
            "type": "rsi_oversold", "level": "info",
            "item_name": "테스트검", "rsi": 25.1,
        }
        embed = build_alert_embed(alert)
        assert "과매도" in embed.title
        assert embed.color.value == 0x2ED573

    def test_fat_finger_high_embed(self):
        """fat_finger_high 알림 → '비정상 고가' 포함."""
        alert = {
            "type": "fat_finger_high", "level": "fun",
            "item_name": "테스트검", "price": 100000,
            "median_price": 10000, "overprice": 900.0,
        }
        embed = build_alert_embed(alert)
        assert "비정상 고가" in embed.title

    def test_fat_finger_embed(self):
        """fat_finger 알림 → '파격세일' 포함."""
        alert = {
            "type": "fat_finger", "level": "fun",
            "item_name": "테스트검", "price": 1000,
            "median_price": 10000, "discount": 90.0,
        }
        embed = build_alert_embed(alert)
        assert "파격세일" in embed.title

    def test_price_above_embed(self):
        """price_above 알림 → '목표가 돌파' 포함."""
        alert = {
            "type": "price_above", "item_name": "테스트검",
            "price": 15000, "target": 14000,
        }
        embed = build_alert_embed(alert)
        assert "목표가 돌파" in embed.title

    def test_price_below_embed(self):
        """price_below 알림 → '지지선 이탈' 포함."""
        alert = {
            "type": "price_below", "item_name": "테스트검",
            "price": 8000, "target": 9000,
        }
        embed = build_alert_embed(alert)
        assert "지지선 이탈" in embed.title

    def test_unknown_type_fallback(self):
        """알 수 없는 타입 → 기본 embed 반환."""
        alert = {
            "type": "unknown_event", "item_name": "테스트검",
        }
        embed = build_alert_embed(alert)
        assert isinstance(embed, discord.Embed)
        assert embed.color.value == 0x95A5A6

    def test_embed_has_timestamp(self):
        """모든 embed에 timestamp가 설정됨."""
        alert = {
            "type": "surge", "level": "urgent",
            "item_name": "테스트검", "change_pct": 35.0, "price": 13500,
        }
        embed = build_alert_embed(alert)
        assert embed.timestamp is not None
