import discord
from discord import app_commands, Interaction

from core.db import get_all_mist_assimilation
from core.models import SERVER_MAP


def _parse_exp_rate(exp_rate: str) -> float:
    try:
        return float(exp_rate.replace("%", ""))
    except (ValueError, AttributeError):
        return 0.0


def _sort_key(row):
    """
    정렬 기준:
    1. level DESC
    2. 만렙(100) 달성자는 max_reached_at ASC (먼저 달성한 순)
    3. 미만렙은 exp_rate DESC
    """
    level = row['level']
    exp = _parse_exp_rate(row['exp_rate'])
    max_reached = row.get('max_reached_at') or ''

    if level >= 100 and max_reached:
        # 만렙: level 높을수록, 달성 시점 빠를수록 상위
        # max_reached를 음수 역전 대신 별도 튜플 그룹으로 분리
        return (1, level, max_reached)
    else:
        # 미만렙: level 높을수록, exp 높을수록 상위
        return (0, level, exp)


@app_commands.command(name="안개융화순위", description="모험단별 안개융화 레벨 순위를 조회합니다.")
async def mist_ranking(interaction: Interaction):
    await interaction.response.defer()

    rows = await get_all_mist_assimilation()
    if not rows:
        await interaction.followup.send("등록된 안개융화 데이터가 없습니다.")
        return

    # 만렙 그룹: 달성 시점 빠른 순 (ASC)
    maxed = [r for r in rows if r['level'] >= 100 and r.get('max_reached_at')]
    maxed.sort(key=lambda r: r['max_reached_at'])

    # 미만렙 그룹: level DESC → exp_rate DESC
    others = [r for r in rows if r not in maxed]
    others.sort(
        key=lambda r: (r['level'], _parse_exp_rate(r['exp_rate'])),
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

    embed = discord.Embed(
        title="🌫️ 안개융화 순위",
        description="\n\n".join(lines),
        color=0x7B68EE,
    )
    await interaction.followup.send(embed=embed)
