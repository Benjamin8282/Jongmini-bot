import discord
from discord import app_commands, Interaction

from core.db import get_all_mist_assimilation
from core.models import SERVER_MAP, parse_exp_rate

MAX_EMBED_DESC = 4000


@app_commands.command(name="안개서약순위", description="모험단별 안개서약 레벨 순위를 조회합니다.")
async def mist_ranking(interaction: Interaction):
    await interaction.response.defer()

    rows = await get_all_mist_assimilation()
    if not rows:
        await interaction.followup.send("등록된 안개서약 데이터가 없습니다.")
        return

    # 만렙 그룹: 달성 시점 빠른 순 (ASC)
    maxed = [r for r in rows if r['level'] >= 100 and r.get('max_reached_at')]
    maxed.sort(key=lambda r: r['max_reached_at'])

    # 미만렙 그룹: level DESC → exp_rate DESC
    maxed_set = set(id(r) for r in maxed)
    others = [r for r in rows if id(r) not in maxed_set]
    others.sort(
        key=lambda r: (r['level'], parse_exp_rate(r['exp_rate'])),
        reverse=True
    )

    sorted_rows = maxed + others

    lines = []
    for i, row in enumerate(sorted_rows, 1):
        server_name = SERVER_MAP.get(row['server_id'], row['server_id'])
        level_str = f"Lv.**{row['level']}**"
        if row['level'] >= 100:
            level_str += " (MAX)"
        else:
            level_str += f" ({row['exp_rate']})"
        lines.append(
            f"**{i}위** | {row['adventure_name']} ({server_name}) | {level_str}"
        )

    description = "\n\n".join(lines)
    if len(description) > MAX_EMBED_DESC:
        description = description[:MAX_EMBED_DESC] + "\n\n...(이하 생략)"

    embed = discord.Embed(
        title="🌫️ 안개서약 순위",
        description=description,
        color=0x7B68EE,
    )
    await interaction.followup.send(embed=embed)
