import asyncio
import discord
from discord import app_commands, Interaction
import aiohttp
import random
import time
from core.db import get_all_characters
from core.logger import logger

# 메모리 캐시: { (character_id, server_id): (timestamp, data) }
_cache = {}
_CACHE_DURATION = 60 * 10  # 10분 캐시 유지 (초 단위)


async def fetch_dundam_data_with_retry(session, character, retries=3):
    key = (character['character_id'], character['server_id'])

    # 캐시 확인 (10분 이내면 캐시 사용)
    now = time.time()
    if key in _cache:
        ts, cached_data = _cache[key]
        if now - ts < _CACHE_DURATION:
            logger.info(f"캐시에서 던담 데이터 사용: {character['character_name']}")
            return cached_data

    url = f"https://dundam.xyz/dat/viewData.jsp?image={character['character_id']}&server={character['server_id']}"

    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    for item in data.get('damageList', {}).get('vsRanking', []):
                        if item.get('name') == '총 합':
                            damage_str = item.get('dam', '0')
                            damage_int = int(damage_str.replace(',', ''))
                            result = {
                                "character_name": character.get('character_name'),
                                "adventure_name": character.get('adventure_name'),
                                "damage": damage_int
                            }
                            _cache[key] = (now, result)  # 캐시에 저장
                            logger.info(f"던담 데이터 조회 성공: {character['character_name']} - 데미지: {damage_int}")
                            return result

                    logger.warning(f"총 합 항목 없음: {character['character_name']}")
                    return None

                elif response.status in (403, 429):
                    wait = (2 ** attempt) + random.random()
                    logger.warning(f"HTTP {response.status} 에러: {character['character_name']} - {wait:.2f}초 후 재시도")
                    await asyncio.sleep(wait)
                else:
                    text = await response.text()
                    logger.error(f"HTTP {response.status} 에러: {character['character_name']} - 응답: {text}")
                    return None

        except Exception as e:
            logger.error(f"던담 데이터 조회 실패: {character['character_name']} - {e}")
            wait = (2 ** attempt) + random.random()
            logger.info(f"예외 발생, {wait:.2f}초 후 재시도")
            await asyncio.sleep(wait)

    logger.error(f"던담 데이터 재시도 실패: {character['character_name']}")
    return None


async def fetch_all_with_rate_limit(session, characters, limit_per_second=5):
    semaphore = asyncio.Semaphore(limit_per_second)
    results = []

    async def limited_fetch(char):
        async with semaphore:
            result = await fetch_dundam_data_with_retry(session, char)
            await asyncio.sleep(1 / limit_per_second)  # 요청 간격 조절
            return result

    tasks = [limited_fetch(char) for char in characters]

    for coro in asyncio.as_completed(tasks):
        res = await coro
        results.append(res)

    return results


@app_commands.command(name="던담순위", description="등록된 모든 캐릭터의 던담 랭킹을 조회합니다.")
async def dundam_ranking(interaction: Interaction):
    """/던담순위 명령어 핸들러"""
    await interaction.response.defer(thinking=True)

    characters = await get_all_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    async with aiohttp.ClientSession() as session:
        results = await fetch_all_with_rate_limit(session, characters, limit_per_second=5)

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
