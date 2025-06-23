from datetime import timedelta, timezone
from discord import app_commands, Interaction

from tasks.weekly_character_aggregation import aggregate_weekly_items_by_character

KST = timezone(timedelta(hours=9))

@app_commands.command(name="주간캐릭터현황", description="최근 목요일 6시부터 현재까지 캐릭터별 아이템 획득량 집계를 보여줍니다.")
async def weekly_character_status(interaction: Interaction):
    await aggregate_weekly_items_by_character(
        interaction.client,
        str(interaction.guild_id),
        interaction = interaction,  # Interaction 객체 전달
    )
