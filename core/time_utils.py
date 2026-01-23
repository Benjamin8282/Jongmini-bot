from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SEASON_START_DATE = datetime(2025, 1, 8, 6, 0, 0, tzinfo=KST)  # 중천 시즌 시작일 오전 6시


def get_weekly_period():
    """한 주 단위 집계 기간을 반환합니다.
    기간: 지난 주 목요일 6시부터 이번 주 목요일 6시까지 (혹은 지금 시각까지)"""
    now = datetime.now(KST)
    weekday = now.weekday()  # 월=0, 화=1, ..., 목=3, ...

    # 이번 주 목요일 6시 구하기
    days_until_thursday = (3 - weekday) % 7
    this_thursday = (now + timedelta(days=days_until_thursday)).replace(hour=6, minute=0, second=0, microsecond=0)

    # 지난 주 목요일 6시 구하기
    last_thursday = this_thursday - timedelta(weeks=1)

    if now >= this_thursday:
        # 현재 시각이 이번 주 목요일 6시 이후면, 한 주 기간은 지난 주 목~이번 주 목 6시
        start_time = last_thursday
        end_time = this_thursday
    else:
        # 현재 시각이 이번 주 목요일 6시 이전이면, 기간은 지난 주 목~현재 시각
        start_time = last_thursday
        end_time = now

    return start_time, end_time


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
