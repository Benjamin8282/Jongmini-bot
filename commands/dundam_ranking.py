import time
import aiohttp
import discord
from discord import app_commands, Interaction
from core.db import get_all_characters
from core.dundam_api import fetch_all_with_rate_limit

def format_score_korean(num: int) -> str:
    if num >= 100_000_000:
        return f"{num // 100_000_000}억 {num % 100_000_000 // 10_000}만"
    elif num >= 10_000:
        return f"{num // 10_000}만 {num % 10_000}"
    else:
        return f"{num}"

@app_commands.command(name="던담순위", description="등록된 모든 캐릭터의 던담 랭킹을 조회합니다.")
async def dundam_ranking(interaction: Interaction):
    await interaction.response.defer(thinking=True)

    characters = await get_all_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    async with aiohttp.ClientSession() as session:
        results = await fetch_all_with_rate_limit(session, characters, limit_per_second=5)

    ranked_characters = sorted([r for r in results if r], key=lambda x: x['damage'], reverse=True)
    top_20_characters = ranked_characters[:20]

    embed = discord.Embed(title="던담 데미지 순위", color=discord.Color.gold())
    embed.set_footer(text=f"기준 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    description = ""
    for i, char in enumerate(top_20_characters, 1):
        score_kor = format_score_korean(char['damage'])
        description += f"**{i}위** **{char.get('character_name', '알 수 없음')}** ({char.get('adventure_name', '알 수 없음')})\n\n"
        description += f"**점수:** {score_kor}\n"

    if not description:
        description = "던담 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다."

    embed.description = description
    await interaction.followup.send(embed=embed)
