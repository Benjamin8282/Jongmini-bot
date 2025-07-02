from discord import app_commands, Interaction
from tasks.daily_aggregation import aggregate_items_and_notify_for_period
from core.time_utils import get_season_period

@app_commands.command(name="시즌현황", description="중천 시즌 시작일(2025-01-08 오전 6시)부터 현재까지의 모험단 아이템 획득량 집계를 보여줍니다.")
async def season_status(interaction: Interaction):
    await interaction.response.defer()

    start_time, end_time = get_season_period()

    embed = await aggregate_items_and_notify_for_period(
        interaction.client,
        str(interaction.guild_id),
        start_time,
        end_time,
        interaction=None,
        period="시즌", # 집계 기간 표시
        need_embed=True  # 임베드 형태로 응답
    )

    await interaction.followup.send(embed=embed)