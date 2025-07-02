from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SEASON_START_DATE = datetime(2025, 1, 8, 6, 0, 0, tzinfo=KST)  # 중천 시즌 시작일 오전 6시

def get_weekly_period():
    """주간 집계 기간(지난 목요일 6시 ~ 현재)을 반환합니다."""
    now = datetime.now(KST)
    weekday = now.weekday()  # 월=0, 화=1, 수=2, 목=3, 금=4, 토=5, 일=6

    # 오늘이 목요일이거나 목요일 이후라면, 이번 주 목요일을 찾음
    # 오늘이 목요일 이전이라면, 지난 주 목요일을 찾음
    days_since_thursday = (weekday - 3 + 7) % 7
    last_thursday = now - timedelta(days=days_since_thursday)
    
    start_time = last_thursday.replace(hour=6, minute=0, second=0, microsecond=0)

    # 만약 현재 시각이 집계 시작 시각보다 이르다면 (예: 목요일 새벽 4시),
    # 집계 시작을 지난 주로 설정해야 함
    if now < start_time:
        start_time -= timedelta(weeks=1)
        
    return start_time, now

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
