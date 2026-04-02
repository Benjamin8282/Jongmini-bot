from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

PREV_SEASON_NAME = "중천"
PREV_SEASON_START = datetime(2025, 1, 8, 6, 0, 0, tzinfo=KST)
PREV_SEASON_END = datetime(2026, 3, 26, 6, 0, 0, tzinfo=KST)

SEASON_NAME = "천해천"
SEASON_START_DATE = datetime(2026, 3, 26, 6, 0, 0, tzinfo=KST)  # 천해천 시즌 시작일 오전 6시


def _current_week_start(now):
    """현재 주의 시작 시각(목요일 06:00)을 반환합니다."""
    weekday = now.weekday()
    days_since_thursday = (weekday - 3) % 7
    thursday = now - timedelta(days=days_since_thursday)
    start = thursday.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=7)
    return start


def get_weekly_period():
    """현재 주 진행 범위 (목요일 06:00 ~ 현재). 커맨드용."""
    now = datetime.now(KST)
    return _current_week_start(now), now


def get_completed_weekly_period():
    """직전 완결 주 범위 (지난 목요일 06:00 ~ 이번 목요일 06:00). 정기 집계용."""
    now = datetime.now(KST)
    week_start = _current_week_start(now)
    prev_week_start = week_start - timedelta(weeks=1)
    return prev_week_start, week_start


def get_monthly_period():
    """월간 집계 기간(이번 달 1일 6시 ~ 현재)을 반환합니다."""
    now = datetime.now(KST)

    # 이번 달 1일 6시
    start_of_month = now.replace(day=1, hour=6, minute=0, second=0, microsecond=0)

    # 만약 현재 시각이 집계 시작 시각보다 이르다면 (예: 1일 새벽 4시),
    # 집계 시작을 지난달 1일로 설정해야 함
    if now < start_of_month:
        # 지난달의 마지막 날을 구하고 day=1을 하여 지난달 1일을 구함
        last_month_last_day = now.replace(day=1) - timedelta(days=1)
        start_time = last_month_last_day.replace(day=1, hour=6, minute=0, second=0, microsecond=0)
    else:
        start_time = start_of_month

    return start_time, now


def get_daily_period():
    """일간 집계 기간(오늘 6시 ~ 현재)을 반환합니다."""
    now = datetime.now(KST)
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < today_6am:
        start_time = today_6am - timedelta(days=1)  # 어제 6시
    else:
        start_time = today_6am  # 오늘 6시
    end_time = now
    return start_time, end_time


def get_daily_aggregation_period():
    """정기 일간 집계 기간(전날 6시 ~ 오늘 5시 59분 59초)을 반환합니다."""
    now = datetime.now(KST)
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    start_time = today_6am - timedelta(days=1)
    end_time = today_6am - timedelta(seconds=1)
    return start_time, end_time


def get_season_period():
    """시즌 집계 기간(시즌 시작일 ~ 현재)을 반환합니다."""
    return SEASON_START_DATE, datetime.now(KST)
