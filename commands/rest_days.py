from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands, Interaction

from core.db import get_all_rest_days_since, get_all_characters_grouped_by_adventure
from core.time_utils import SEASON_START_DATE, SEASON_NAME

KST = timezone(timedelta(hours=9))


def _calc_streaks(rest_dates: list[str], season_start_str: str, today_str: str):
    """현재 연속, 최장 연속, 마지막 접속일 계산."""
    date_set = set(rest_dates)

    # 시즌 시작일 ~ 어제까지의 전체 날짜 생성
    start = datetime.strptime(season_start_str, "%Y-%m-%d").date()
    today = datetime.strptime(today_str, "%Y-%m-%d").date()
    yesterday = today - timedelta(days=1)

    # 현재 연속: 어제부터 거슬러 올라감
    current_streak = 0
    d = yesterday
    while d >= start and d.isoformat() in date_set:
        current_streak += 1
        d -= timedelta(days=1)

    # 최장 연속
    max_streak = 0
    streak = 0
    d = start
    while d <= yesterday:
        if d.isoformat() in date_set:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
        d += timedelta(days=1)

    # 마지막 접속일 (쉬었음이 아닌 마지막 날)
    last_active = None
    d = yesterday
    while d >= start:
        if d.isoformat() not in date_set:
            last_active = d.isoformat()
            break
        d -= timedelta(days=1)

    return {
        "current_streak": current_streak,
        "max_streak": max_streak,
        "last_active": last_active,
    }


def _pick_icon(total: int, current_streak: int) -> str:
    if total == 0:
        return "✅"
    if current_streak >= 3:
        return "🏕️"
    if current_streak >= 1:
        return "😴"
    return "📋"


def _build_embed(
    all_rest: dict[str, list[str]],
    all_adventures: list[str],
    season_start_str: str,
    today_str: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"쉬었음 현황 ({SEASON_NAME} 시즌)",
        description=f"시즌 시작: {season_start_str}",
        color=0x95A5A6,
    )

    # 모험단을 쉬었음 일수 내림차순 정렬
    adventure_stats = []
    for adv in all_adventures:
        dates = all_rest.get(adv, [])
        stats = _calc_streaks(dates, season_start_str, today_str)
        stats["total"] = len(dates)
        stats["adventure"] = adv
        adventure_stats.append(stats)

    adventure_stats.sort(key=lambda x: x["total"], reverse=True)

    for s in adventure_stats:
        icon = _pick_icon(s["total"], s["current_streak"])
        lines = [f"총 **{s['total']}일** 쉬었음"]
        if s["current_streak"] > 0:
            lines.append(f"현재 **{s['current_streak']}일** 연속 쉬는 중 🔥")
        if s["max_streak"] > 0:
            lines.append(f"최장 연속: {s['max_streak']}일")
        if s["last_active"]:
            lines.append(f"마지막 접속: {s['last_active']}")
        elif s["total"] == 0:
            lines.append("개근!")

        embed.add_field(
            name=f"{icon} {s['adventure']}",
            value="\n".join(lines),
            inline=False,
        )

    if not adventure_stats:
        embed.description += "\n\n등록된 모험단이 없습니다."

    return embed


@app_commands.command(
    name="쉬었음",
    description="모험단별 쉬었음(미접속) 일수를 조회합니다"
)
async def rest_days_cmd(interaction: Interaction):
    await interaction.response.defer()

    season_start_str = SEASON_START_DATE.strftime("%Y-%m-%d")
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    grouped = await get_all_characters_grouped_by_adventure()
    all_adventures = list(grouped.keys()) if grouped else []

    all_rest = await get_all_rest_days_since(season_start_str)

    embed = _build_embed(all_rest, all_adventures, season_start_str, today_str)
    await interaction.followup.send(embed=embed)
