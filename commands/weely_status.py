from discord import app_commands, Interaction
from datetime import datetime, timedelta, timezone
from tasks.daily_aggregation import aggregate_items_and_notify_for_period  # 집계 함수 재활용

KST = timezone(timedelta(hours=9))

def get_last_thursday_6am(now: datetime):
    weekday = now.weekday()  # 월=0, 목=3, 일=6
    days_since_thursday = (weekday - 3) % 7
    last_thursday = now - timedelta(days=days_since_thursday)
    last_thursday_6am = last_thursday.replace(hour=6, minute=0, second=0, microsecond=0)
    # 만약 현재가 목요일 6시 이전이면 한 주 전 목요일 6시를 반환
    if now < last_thursday_6am:
        last_thursday_6am -= timedelta(days=7)
    return last_thursday_6am

@app_commands.command(name="주간현황", description="최근 목요일 6시부터 현재까지의 모험단 아이템 획득량 집계를 보여줍니다.")
async def weekly_status(interaction: Interaction):
    now = datetime.now(KST)
    start_time = get_last_thursday_6am(now)
    end_time = now

    await aggregate_items_and_notify_for_period(
        interaction.client,
        str(interaction.guild_id),
        start_time,
        end_time,
        interaction=interaction  # 명령어 응답용 interaction 전달
    )
