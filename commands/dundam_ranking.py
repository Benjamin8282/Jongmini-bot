
import asyncio
import discord
from discord import app_commands, Interaction
from core.db import get_all_characters
from core.logger import logger
import aiohttp

async def fetch_dundam_data(session, character, semaphore):
    """캐릭터의 던담 데이터를 비동기적으로 가져옵니다."""
    url = f"https://dundam.xyz/dat/viewData.jsp?image={character['character_id']}&server={character['server_id']}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json(content_type=None)
                for item in data.get('damageList', {}).get('vsRanking', []):
                    if item.get('name') == '총 합':
                        damage_str = item.get('dam', '0')
                        damage_int = int(damage_str.replace(',', ''))
                        logger.info(f"던담 데이터 조회 성공: {character['character_name']} - 데미지: {damage_int}")
                        return {
                            "character_name": character.get('character_name'),
                            "adventure_name": character.get('adventure_name'),
                            "damage": damage_int
                        }
    except Exception as e:
        logger.error(f"던담 데이터 조회 실패: {character['character_name']} - {e}")
    return None

@app_commands.command(name="던담순위", description="등록된 모든 캐릭터의 던담 랭킹을 조회합니다.")
async def dundam_ranking(interaction: Interaction):
    """/던담순위 명령어 핸들러"""
    await interaction.response.defer(thinking=True)
    
    characters = await get_all_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    semaphore = asyncio.Semaphore(10)
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_dundam_data(session, char, semaphore) for char in characters]
        results = await asyncio.gather(*tasks)

    # 피해량 순으로 정렬
    ranked_characters = sorted([r for r in results if r], key=lambda x: x['damage'], reverse=True)

    # 상위 20개 캐릭터만 표시
    top_20_characters = ranked_characters[:20]

    embed = discord.Embed(title="던담 랭킹 (상위 20)", color=discord.Color.gold())
    
    if not top_20_characters:
        embed.description = "던담 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다."
    else:
        description = ""
        for i, char in enumerate(top_20_characters):
            description += f"{i+1}. **{char.get('character_name', '알 수 없음')}** ({char.get('adventure_name', '알 수 없음')}) - 데미지: {char.get('damage', 0):,}\n"
        embed.description = description

    await interaction.followup.send(embed=embed)
