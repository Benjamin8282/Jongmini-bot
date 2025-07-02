from discord import app_commands, Interaction
from tasks.daily_aggregation import aggregate_items_and_notify_for_period
from core.time_utils import get_monthly_period

@app_commands.command(name="월간현황", description="이번 달 1일 6시부터 현재까지의 모험단 아이템 획득량 집계를 보여줍니다.")
async def monthly_status(interaction: Interaction):
    await interaction.response.defer()

    start_time, end_time = get_monthly_period()

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
