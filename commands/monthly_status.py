from discord import app_commands, Interaction
from datetime import datetime, timedelta, timezone
from tasks.daily_aggregation import aggregate_items_and_notify_for_period  # 집계 함수 재활용

KST = timezone(timedelta(hours=9))

def get_month_start_6am(now: datetime):
    # 이번 달 1일 06:00 시각 반환
    month_start = now.replace(day=1, hour=6, minute=0, second=0, microsecond=0)
    # 만약 현재 시각이 1일 6시 이전이라면, 이전 달 1일 6시를 반환
    if now < month_start:
        # 이전 달 1일로 계산
        year = now.year
        month = now.month - 1
        if month == 0:
            month = 12
            year -= 1
        month_start = month_start.replace(year=year, month=month)
    return month_start

@app_commands.command(name="월간현황", description="이번 달 1일 6시부터 현재까지의 모험단 아이템 획득량 집계를 보여줍니다.")
async def monthly_status(interaction: Interaction):
    await interaction.response.defer()

    now = datetime.now(KST)
    start_time = get_month_start_6am(now)
    end_time = now

    embed = await aggregate_items_and_notify_for_period(
        interaction.client,
        str(interaction.guild_id),
        start_time,
        end_time,
        interaction=None,  # 실제 응답은 followup으로 보내기 때문에 None으로 넘김
        period="월간",  # 집계 기간 표시
        need_embed=True
    )

    await interaction.followup.send(embed=embed)
