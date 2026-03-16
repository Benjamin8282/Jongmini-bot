"""tasks/morning_briefing.py 순수 로직 함수 테스트."""
from datetime import datetime, timedelta

import discord
import pytest

from tasks.morning_briefing import (
    _calc_price_change_pct,
    _calc_volume_stats,
    _build_item_result,
    _calc_market_aggregates,
    _arrow_for,
    _color_for_change,
    _build_market_summary_embed,
    _build_briefing_embeds,
    KST,
)

# ─── 공통 샘플 데이터 ───


@pytest.fixture
def sample_items_data():
    """테스트용 아이템 데이터 리스트."""
    return [
        {
            "name": "테스트검",
            "item_id": "abc",
            "prices": [100, 110, 120],
            "current": 120,
            "change_pct": 20.0,
            "high": 130,
            "low": 90,
            "volume": 50,
            "volume_prev": 40,
            "volume_change_pct": 25.0,
            "signal": None,
        },
        {
            "name": "테스트방패",
            "item_id": "def",
            "prices": [200, 190, 180],
            "current": 180,
            "change_pct": -10.0,
            "high": 210,
            "low": 175,
            "volume": 30,
            "volume_prev": 50,
            "volume_change_pct": -40.0,
            "signal": "golden_cross",
        },
    ]


@pytest.fixture
def sample_records_24h():
    """24시간 가격 레코드."""
    now = datetime.now(KST)
    records = []
    for i in range(10):
        dt = now - timedelta(hours=10 - i)
        records.append({
            "sold_date": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "unit_price": 1000 + i * 100,
            "count": 5,
        })
    return records


@pytest.fixture
def sample_records_48h():
    """48시간 가격 레코드 (24시간 이전 포함)."""
    now = datetime.now(KST)
    records = []
    # 24시간 이전 데이터
    for i in range(10):
        dt = now - timedelta(hours=48 - i)
        records.append({
            "sold_date": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "unit_price": 900 + i * 50,
            "count": 3,
        })
    # 24시간 이내 데이터
    for i in range(10):
        dt = now - timedelta(hours=10 - i)
        records.append({
            "sold_date": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "unit_price": 1000 + i * 100,
            "count": 5,
        })
    return records


# ═══════════════════════════════════════════════
# _calc_price_change_pct 테스트
# ═══════════════════════════════════════════════


class TestCalcPriceChangePct:
    """첫 가격 대비 마지막 가격 변동률 계산 테스트."""

    def test_normal_increase(self):
        """정상 상승: (120-100)/100 * 100 = 20.0%."""
        prices = [100, 110, 120]
        assert _calc_price_change_pct(prices) == pytest.approx(20.0)

    def test_normal_decrease(self):
        """정상 하락: (80-100)/100 * 100 = -20.0%."""
        prices = [100, 90, 80]
        assert _calc_price_change_pct(prices) == pytest.approx(-20.0)

    def test_no_change(self):
        """변동 없음: 0%."""
        prices = [100, 100, 100]
        assert _calc_price_change_pct(prices) == pytest.approx(0.0)

    def test_first_price_zero(self):
        """첫 가격이 0이면 ZeroDivision 방지 → 0 반환."""
        prices = [0, 100, 200]
        assert _calc_price_change_pct(prices) == 0

    def test_two_prices(self):
        """가격 2개만 있는 최소 케이스."""
        prices = [1000, 1500]
        assert _calc_price_change_pct(prices) == pytest.approx(50.0)

    def test_large_increase(self):
        """큰 상승폭."""
        prices = [100, 500, 1000]
        assert _calc_price_change_pct(prices) == pytest.approx(900.0)


# ═══════════════════════════════════════════════
# _calc_volume_stats 테스트
# ═══════════════════════════════════════════════


class TestCalcVolumeStats:
    """24시간/전일 거래량 및 변동률 계산 테스트."""

    def test_normal_volume(self, sample_records_24h, sample_records_48h):
        """정상 거래량 계산."""
        now = datetime.now(KST)
        boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

        volume, prev_volume, change = _calc_volume_stats(
            sample_records_24h, sample_records_48h, boundary
        )
        # records_24h: 10건 * count=5 = 50
        assert volume == 50
        assert prev_volume > 0
        assert isinstance(change, float)

    def test_no_previous_records(self, sample_records_24h):
        """이전 기간 데이터가 없을 때."""
        # boundary를 먼 과거로 설정 → 48h 레코드가 모두 24h 내이므로 이전 레코드 없음
        boundary = "2000-01-01 00:00:00"

        volume, prev_volume, change = _calc_volume_stats(
            sample_records_24h, sample_records_24h, boundary
        )
        assert volume == 50  # 10 * 5
        assert prev_volume == 0
        assert change == 0  # previous=0이면 0 반환

    def test_empty_24h_records(self):
        """24시간 데이터가 없을 때."""
        now = datetime.now(KST)
        boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        volume, prev_volume, change = _calc_volume_stats(
            [], [], boundary
        )
        assert volume == 0
        assert prev_volume == 0

    def test_volume_increase(self):
        """거래량 증가 시 양수 변동률."""
        now = datetime.now(KST)
        boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

        # 24시간: count=10 * 5건 = 50
        records_24h = [
            {"sold_date": now.strftime("%Y-%m-%d %H:%M:%S"),
             "unit_price": 1000, "count": 10}
            for _ in range(5)
        ]
        # 48시간: 이전 기간에 count=5 * 5건 = 25
        prev_time = now - timedelta(hours=30)
        records_48h = [
            {"sold_date": prev_time.strftime("%Y-%m-%d %H:%M:%S"),
             "unit_price": 1000, "count": 5}
            for _ in range(5)
        ] + records_24h

        volume, prev_volume, change = _calc_volume_stats(
            records_24h, records_48h, boundary
        )
        assert volume == 50
        assert prev_volume == 25
        assert change == pytest.approx(100.0)  # (50-25)/25 * 100


# ═══════════════════════════════════════════════
# _build_item_result 테스트
# ═══════════════════════════════════════════════


class TestBuildItemResult:
    """단일 아이템 24시간 분석 결과 생성 테스트."""

    def test_normal_result(self, sample_records_24h, sample_records_48h):
        """정상 결과 생성."""
        now = datetime.now(KST)
        boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

        result = _build_item_result(
            "테스트검", "item_1",
            sample_records_24h, sample_records_48h, boundary, None
        )
        assert result is not None
        assert result["name"] == "테스트검"
        assert result["item_id"] == "item_1"
        assert result["current"] == sample_records_24h[-1]["unit_price"]
        assert result["high"] == max(r["unit_price"] for r in sample_records_24h)
        assert result["low"] == min(r["unit_price"] for r in sample_records_24h)
        assert result["signal"] is None
        assert isinstance(result["change_pct"], float)
        assert isinstance(result["volume"], int)

    def test_insufficient_records_returns_none(self):
        """레코드가 2개 미만이면 None 반환."""
        now = datetime.now(KST)
        boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        single_record = [{
            "sold_date": now.strftime("%Y-%m-%d %H:%M:%S"),
            "unit_price": 1000, "count": 1,
        }]

        result = _build_item_result(
            "테스트검", "item_1", single_record, single_record, boundary, None
        )
        assert result is None

    def test_empty_records_returns_none(self):
        """빈 레코드면 None 반환."""
        now = datetime.now(KST)
        boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        result = _build_item_result("테스트검", "item_1", [], [], boundary, None)
        assert result is None

    def test_with_signal(self, sample_records_24h, sample_records_48h):
        """시그널이 있을 때 결과에 포함."""
        now = datetime.now(KST)
        boundary = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

        result = _build_item_result(
            "테스트검", "item_1",
            sample_records_24h, sample_records_48h, boundary,
            "golden_cross"
        )
        assert result is not None
        assert result["signal"] == "golden_cross"


# ═══════════════════════════════════════════════
# _calc_market_aggregates 테스트
# ═══════════════════════════════════════════════


class TestCalcMarketAggregates:
    """시장 전체 집계 지표 계산 테스트."""

    def test_aggregation(self, sample_items_data):
        """복수 아이템 집계 결과 검증."""
        agg = _calc_market_aggregates(sample_items_data)

        # 총 거래량: 50 + 30 = 80
        assert agg["total_volume"] == 80
        # 평균 변동률: (20.0 + (-10.0)) / 2 = 5.0
        assert agg["avg_change"] == pytest.approx(5.0)
        # 상승/하락/보합: 1 up, 1 down, 0 flat
        assert agg["up_count"] == 1
        assert agg["down_count"] == 1
        assert agg["flat_count"] == 0

    def test_all_up(self):
        """모두 상승인 경우."""
        data = [
            {"change_pct": 10.0, "volume": 100, "volume_prev": 80},
            {"change_pct": 5.0, "volume": 50, "volume_prev": 40},
        ]
        agg = _calc_market_aggregates(data)
        assert agg["up_count"] == 2
        assert agg["down_count"] == 0
        assert agg["flat_count"] == 0

    def test_all_down(self):
        """모두 하락인 경우."""
        data = [
            {"change_pct": -10.0, "volume": 100, "volume_prev": 120},
            {"change_pct": -5.0, "volume": 50, "volume_prev": 60},
        ]
        agg = _calc_market_aggregates(data)
        assert agg["up_count"] == 0
        assert agg["down_count"] == 2

    def test_flat(self):
        """모두 보합인 경우."""
        data = [
            {"change_pct": 0.0, "volume": 100, "volume_prev": 100},
        ]
        agg = _calc_market_aggregates(data)
        assert agg["flat_count"] == 1
        assert agg["up_count"] == 0
        assert agg["down_count"] == 0

    def test_volume_change_calculation(self):
        """전체 거래량 변동률 계산."""
        data = [
            {"change_pct": 0.0, "volume": 100, "volume_prev": 50},
            {"change_pct": 0.0, "volume": 200, "volume_prev": 150},
        ]
        agg = _calc_market_aggregates(data)
        # total_volume=300, total_prev=200 → (300-200)/200*100 = 50%
        assert agg["vol_total_change"] == pytest.approx(50.0)

    def test_zero_prev_volume(self):
        """이전 기간 거래량이 0일 때."""
        data = [
            {"change_pct": 0.0, "volume": 100, "volume_prev": 0},
        ]
        agg = _calc_market_aggregates(data)
        assert agg["vol_total_change"] == 0  # previous=0이면 0 반환

    def test_single_item(self):
        """아이템 1개일 때."""
        data = [
            {"change_pct": 15.0, "volume": 200, "volume_prev": 180},
        ]
        agg = _calc_market_aggregates(data)
        assert agg["avg_change"] == pytest.approx(15.0)
        assert agg["total_volume"] == 200


# ═══════════════════════════════════════════════
# _arrow_for / _color_for_change 테스트
# ═══════════════════════════════════════════════


class TestArrowFor:
    """값의 부호에 따른 화살표 반환 테스트."""

    def test_positive(self):
        assert _arrow_for(10.0) == "▲"

    def test_negative(self):
        assert _arrow_for(-10.0) == "▼"

    def test_zero(self):
        assert _arrow_for(0) == "−"

    def test_small_positive(self):
        assert _arrow_for(0.001) == "▲"

    def test_small_negative(self):
        assert _arrow_for(-0.001) == "▼"


class TestColorForChange:
    """변동률에 따른 embed 색상 반환 테스트."""

    def test_positive_red(self):
        """양수 → 빨간색 (상승)."""
        assert _color_for_change(10.0) == 0xE74C3C

    def test_negative_blue(self):
        """음수 → 파란색 (하락)."""
        assert _color_for_change(-10.0) == 0x3498DB

    def test_zero_gray(self):
        """0 → 회색 (보합)."""
        assert _color_for_change(0) == 0x95A5A6


# ═══════════════════════════════════════════════
# _build_market_summary_embed 테스트
# ═══════════════════════════════════════════════


class TestBuildMarketSummaryEmbed:
    """시장 종합 embed 생성 테스트."""

    def test_returns_embed(self, sample_items_data):
        """Embed 객체 반환 확인."""
        now = datetime.now(KST)
        embed = _build_market_summary_embed(sample_items_data, now)
        assert isinstance(embed, discord.Embed)

    def test_embed_title(self, sample_items_data):
        """Embed 제목이 '경제 브리핑'."""
        now = datetime.now(KST)
        embed = _build_market_summary_embed(sample_items_data, now)
        assert embed.title == "경제 브리핑"

    def test_embed_description_has_date(self, sample_items_data):
        """Embed 설명에 날짜 포함."""
        now = datetime.now(KST)
        embed = _build_market_summary_embed(sample_items_data, now)
        date_str = now.strftime("%Y년 %m월 %d일")
        assert date_str in embed.description

    def test_embed_has_fields(self, sample_items_data):
        """Embed에 3개의 필드 (평균 변동률, 총 거래량, 상승/하락/보합)."""
        now = datetime.now(KST)
        embed = _build_market_summary_embed(sample_items_data, now)
        assert len(embed.fields) == 3
        field_names = [f.name for f in embed.fields]
        assert "시장 평균 변동률" in field_names
        assert "총 거래량" in field_names
        assert "상승/하락/보합" in field_names

    def test_embed_color_positive(self):
        """평균 변동률 양수 → 빨간색."""
        data = [
            {"change_pct": 20.0, "volume": 100, "volume_prev": 80},
        ]
        now = datetime.now(KST)
        embed = _build_market_summary_embed(data, now)
        assert embed.color.value == 0xE74C3C

    def test_embed_color_negative(self):
        """평균 변동률 음수 → 파란색."""
        data = [
            {"change_pct": -20.0, "volume": 100, "volume_prev": 120},
        ]
        now = datetime.now(KST)
        embed = _build_market_summary_embed(data, now)
        assert embed.color.value == 0x3498DB


# ═══════════════════════════════════════════════
# _build_briefing_embeds 테스트
# ═══════════════════════════════════════════════


class TestBuildBriefingEmbeds:
    """브리핑 embed 목록 생성 테스트."""

    def test_returns_list_of_embeds(self, sample_items_data):
        """embed 리스트 반환."""
        embeds = _build_briefing_embeds(sample_items_data)
        assert isinstance(embeds, list)
        assert all(isinstance(e, discord.Embed) for e in embeds)

    def test_minimum_two_embeds(self, sample_items_data):
        """최소 2개 embed (시장 종합 + 아이템별 변동)."""
        embeds = _build_briefing_embeds(sample_items_data)
        assert len(embeds) >= 2

    def test_signal_adds_third_embed(self, sample_items_data):
        """시그널이 있으면 3번째 embed (추세 시그널) 추가."""
        # sample_items_data[1]에 golden_cross 시그널이 있음
        embeds = _build_briefing_embeds(sample_items_data)
        assert len(embeds) == 3
        assert embeds[2].title == "추세 시그널"

    def test_no_signal_two_embeds(self):
        """시그널이 없으면 embed 2개만."""
        data = [
            {
                "name": "테스트검",
                "item_id": "abc",
                "prices": [100, 110, 120],
                "current": 120,
                "change_pct": 20.0,
                "high": 130,
                "low": 90,
                "volume": 50,
                "volume_prev": 40,
                "volume_change_pct": 25.0,
                "signal": None,
            },
        ]
        embeds = _build_briefing_embeds(data)
        assert len(embeds) == 2

    def test_first_embed_is_market_summary(self, sample_items_data):
        """첫 번째 embed는 시장 종합."""
        embeds = _build_briefing_embeds(sample_items_data)
        assert embeds[0].title == "경제 브리핑"

    def test_second_embed_is_price_change(self, sample_items_data):
        """두 번째 embed는 아이템별 시세 변동."""
        embeds = _build_briefing_embeds(sample_items_data)
        assert "시세 변동" in embeds[1].title

    def test_price_change_embed_has_item_fields(self, sample_items_data):
        """아이템별 시세 변동 embed에 아이템 필드 포함."""
        embeds = _build_briefing_embeds(sample_items_data)
        price_embed = embeds[1]
        field_names = [f.name for f in price_embed.fields]
        assert "테스트검" in field_names
        assert "테스트방패" in field_names

    def test_items_sorted_by_change_pct(self, sample_items_data):
        """아이템이 변동률 내림차순으로 정렬됨."""
        embeds = _build_briefing_embeds(sample_items_data)
        price_embed = embeds[1]
        # 첫 번째 필드가 가장 높은 변동률 아이템
        assert price_embed.fields[0].name == "테스트검"  # +20%
        assert price_embed.fields[1].name == "테스트방패"  # -10%
