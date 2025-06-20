from discord import app_commands, Interaction
from datetime import datetime, timedelta
from tasks.daily_aggregation import aggregate_items_and_notify_for_period  # 기간 지정 집계 함수
import pytz

KST = pytz.timezone('Asia/Seoul')


def get_today_period(now: datetime):
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < today_6am:
        start_time = today_6am - timedelta(days=1)  # 어제 6시
    else:
        start_time = today_6am  # 오늘 6시
    end_time = now
    return start_time, end_time


@app_commands.command(name="오늘현황", description="오늘 지금까지의 모험단 아이템 획득량을 집계해 보여줍니다.")
async def today_status(interaction: Interaction):
    now = datetime.now(KST)
    start_time, end_time = get_today_period(now)

    await aggregate_items_and_notify_for_period(
        interaction.client,  # 봇 인스턴스
        str(interaction.guild_id),  # 길드 ID
        start_time,
        end_time
    )

    await interaction.response.send_message(
        f"오늘 {start_time.strftime('%m/%d %H:%M')}부터 {end_time.strftime('%m/%d %H:%M')}까지 집계를 완료했습니다.",
        ephemeral=True
    )
