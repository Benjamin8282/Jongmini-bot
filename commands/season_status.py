from discord import app_commands, Interaction
from tasks.daily_aggregation import aggregate_items_and_notify_for_period
from core.time_utils import get_season_period, SEASON_NAME


@app_commands.command(
    name="시즌현황",
    description="현재 시즌 시작일부터 현재까지의 모험단 아이템 획득량 집계를 보여줍니다."
)
async def season_status(interaction: Interaction):
    await interaction.response.defer()

    start_time, end_time = get_season_period()

    embed, _ = await aggregate_items_and_notify_for_period(
        interaction.client,
        str(interaction.guild_id),
        start_time,
        end_time,
        interaction=None,
        period=f"{SEASON_NAME} 시즌",
        need_embed=True
    )

    await interaction.followup.send(embed=embed)
