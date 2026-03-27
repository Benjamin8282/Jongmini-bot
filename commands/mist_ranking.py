import discord
from discord import app_commands, Interaction

from core.db import get_all_mist_assimilation
from core.models import SERVER_MAP


def _parse_exp_rate(exp_rate: str) -> float:
    try:
        return float(exp_rate.replace("%", ""))
    except (ValueError, AttributeError):
        return 0.0


@app_commands.command(name="안개융화순위", description="모험단별 안개융화 레벨 순위를 조회합니다.")
async def mist_ranking(interaction: Interaction):
    await interaction.response.defer()

    rows = await get_all_mist_assimilation()
    if not rows:
        await interaction.followup.send("등록된 안개융화 데이터가 없습니다.")
        return

    # level DESC, exp_rate DESC 정렬
    rows.sort(key=lambda r: (r['level'], _parse_exp_rate(r['exp_rate'])), reverse=True)

    lines = []
    for i, row in enumerate(rows, 1):
        server_name = SERVER_MAP.get(row['server_id'], row['server_id'])
        lines.append(
            f"**{i}위** | {row['adventure_name']} ({server_name}) "
            f"| Lv.**{row['level']}** ({row['exp_rate']})"
        )

    embed = discord.Embed(
        title="🌫️ 안개융화 순위",
        description="\n".join(lines),
        color=0x7B68EE,
    )
    await interaction.followup.send(embed=embed)
