from discord import app_commands, Interaction
from tasks.daily_aggregation import aggregate_items_and_notify_for_period
from core.time_utils import get_weekly_period


@app_commands.command(name="주간현황", description="최근 목요일 6시부터 현재까지의 모험단 아이템 획득량 집계를 보여줍니다.")
async def weekly_status(interaction: Interaction):
    start_time, end_time = get_weekly_period()

    await aggregate_items_and_notify_for_period(
        interaction.client,
        str(interaction.guild_id),
        start_time,
        end_time,
        interaction=interaction,  # 명령어 응답용 interaction 전달
        period="주간"  # 집계 기간 표시
    )
