"""core.time_utils 모듈 테스트."""
from datetime import datetime, timedelta

from core.time_utils import (
    KST,
    SEASON_START_DATE,
    get_daily_aggregation_period,
    get_daily_period,
    get_monthly_period,
    get_season_period,
    get_weekly_period,
)


# ─── get_daily_period ───


def test_daily_period_시작_6시():
    """일간 기간의 시작은 6시 정각이다."""
    start, end = get_daily_period()
    assert start.hour == 6
    assert start.minute == 0
    assert start.second == 0


def test_daily_period_start_lte_end():
    """일간 기간의 start <= end 이다."""
    start, end = get_daily_period()
    assert start <= end


def test_daily_period_KST_타임존():
    """일간 기간은 KST 타임존이다."""
    start, end = get_daily_period()
    assert start.tzinfo == KST
    assert end.tzinfo == KST


def test_daily_period_당일_범위():
    """일간 기간은 최대 24시간 이내이다."""
    start, end = get_daily_period()
    diff = end - start
    assert diff <= timedelta(days=1)


# ─── get_weekly_period ───


def test_weekly_period_목요일_시작():
    """주간 기간의 시작은 목요일(weekday=3)이다."""
    start, end = get_weekly_period()
    assert start.weekday() == 3  # 목요일


def test_weekly_period_시작_6시():
    """주간 기간의 시작은 6시 정각이다."""
    start, end = get_weekly_period()
    assert start.hour == 6
    assert start.minute == 0
    assert start.second == 0


def test_weekly_period_7일_이내():
    """주간 기간은 최대 7일이다."""
    start, end = get_weekly_period()
    diff = end - start
    assert diff <= timedelta(days=7)


def test_weekly_period_start_lte_end():
    """주간 기간의 start <= end 이다."""
    start, end = get_weekly_period()
    assert start <= end


def test_weekly_period_KST_타임존():
    """주간 기간은 KST 타임존이다."""
    start, end = get_weekly_period()
    assert start.tzinfo == KST
    assert end.tzinfo == KST


# ─── get_monthly_period ───


def test_monthly_period_1일_시작():
    """월간 기간의 시작은 1일이다."""
    start, end = get_monthly_period()
    assert start.day == 1


def test_monthly_period_시작_6시():
    """월간 기간의 시작은 6시 정각이다."""
    start, end = get_monthly_period()
    assert start.hour == 6
    assert start.minute == 0
    assert start.second == 0


def test_monthly_period_start_lte_end():
    """월간 기간의 start <= end 이다."""
    start, end = get_monthly_period()
    assert start <= end


def test_monthly_period_KST_타임존():
    """월간 기간은 KST 타임존이다."""
    start, end = get_monthly_period()
    assert start.tzinfo == KST
    assert end.tzinfo == KST


def test_monthly_period_같은_달_또는_전달():
    """월간 기간의 start 월은 end 월과 같거나 직전 달이다."""
    start, end = get_monthly_period()
    # 동일 월이거나, start가 전달 (1일 새벽 엣지 케이스)
    month_diff = (end.year * 12 + end.month) - (start.year * 12 + start.month)
    assert month_diff in (0, 1)


# ─── get_daily_aggregation_period ───


def test_daily_aggregation_period_어제_6시_시작():
    """정기 집계 기간은 어제 6시부터 시작한다."""
    start, end = get_daily_aggregation_period()
    now = datetime.now(KST)
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    expected_start = today_6am - timedelta(days=1)
    assert start == expected_start


def test_daily_aggregation_period_오늘_5시59분59초_종료():
    """정기 집계 기간은 오늘 5시 59분 59초에 끝난다."""
    start, end = get_daily_aggregation_period()
    assert end.hour == 5
    assert end.minute == 59
    assert end.second == 59


def test_daily_aggregation_period_24시간_범위():
    """정기 집계 기간은 정확히 24시간 - 1초이다."""
    start, end = get_daily_aggregation_period()
    diff = end - start
    expected = timedelta(hours=23, minutes=59, seconds=59)
    assert diff == expected


def test_daily_aggregation_period_KST_타임존():
    """정기 집계 기간은 KST 타임존이다."""
    start, end = get_daily_aggregation_period()
    assert start.tzinfo == KST
    assert end.tzinfo == KST


# ─── get_season_period ───


def test_season_period_시작일():
    """시즌 기간의 시작은 SEASON_START_DATE 이다."""
    start, end = get_season_period()
    assert start == SEASON_START_DATE


def test_season_period_KST_타임존():
    """시즌 기간은 KST 타임존이다."""
    start, end = get_season_period()
    assert start.tzinfo == KST
    assert end.tzinfo == KST


def test_season_period_start_lte_end():
    """시즌 기간의 start <= end 이다."""
    start, end = get_season_period()
    assert start <= end


def test_season_period_end_는_현재_근처():
    """시즌 기간의 end 는 현재 시각 근처이다."""
    _, end = get_season_period()
    now = datetime.now(KST)
    # 함수 호출과 now 사이 차이가 1초 이내
    assert abs((now - end).total_seconds()) < 2
