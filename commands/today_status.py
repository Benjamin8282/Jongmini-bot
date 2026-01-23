from discord import app_commands, Interaction
from tasks.daily_aggregation import aggregate_items_and_notify_for_period  # 기간 지정 집계 함수
from core.time_utils import get_daily_period


@app_commands.command(name="오늘현황", description="오늘 지금까지의 모험단 아이템 획득량을 집계해 보여줍니다.")
async def today_status(interaction: Interaction):
    start_time, end_time = get_daily_period()

    await aggregate_items_and_notify_for_period(
        interaction.client,  # 봇 인스턴스
        str(interaction.guild_id),  # 길드 ID
        start_time,
        end_time,
        interaction=interaction,
        period="일간"
    )
