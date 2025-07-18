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


def format_score_korean(num: int) -> str:
    if num >= 100_000_000:
        return f"{num // 100_000_000}억 {num % 100_000_000 // 10_000}만"
    elif num >= 10_000:
        return f"{num // 10_000}만 {num % 10_000}"
    else:
        return f"{num}"


async def fetch_dundam_data_with_retry(session, character, retries=3):
    key = (character['character_id'], character['server_id'])

    now = time.time()
    if key in _cache:
        ts, cached_data = _cache[key]
        if now - ts < _CACHE_DURATION:
            logger.info("캐시에서 던담 데이터 사용: %s", character['character_name'])
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
                            _cache[key] = (now, result)
                            logger.info("던담 데이터 조회 성공: %s - 데미지: %d", character['character_name'], damage_int)
                            return result

                    logger.warning("총 합 항목 없음: %s", character['character_name'])
                    return None

                elif response.status in (403, 429):
                    wait = (2 ** attempt) + random.random()
                    logger.warning("HTTP %d 에러: %s - %.2f초 후 재시도", response.status, character['character_name'], wait)
                    await asyncio.sleep(wait)
                else:
                    text = await response.text()
                    logger.error("HTTP %d 에러: %s - 응답: %s", response.status, character['character_name'], text)
                    return None

        except Exception as e:
            logger.error("던담 데이터 조회 실패: %s - %s", character['character_name'], e)
            wait = (2 ** attempt) + random.random()
            logger.info("예외 발생, %.2f초 후 재시도", wait)
            await asyncio.sleep(wait)

    logger.error("던담 데이터 재시도 실패: %s", character['character_name'])
    return None


async def fetch_all_with_rate_limit(session, characters, limit_per_second=5):
    semaphore = asyncio.Semaphore(limit_per_second)
    results = []

    async def limited_fetch(char):
        async with semaphore:
            result = await fetch_dundam_data_with_retry(session, char)
            await asyncio.sleep(1 / limit_per_second)
            return result

    tasks = [limited_fetch(char) for char in characters]

    for coro in asyncio.as_completed(tasks):
        res = await coro
        results.append(res)

    return results


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
        description += f"**{i}위** **{char.get('character_name', '알 수 없음')}** ({char.get('adventure_name', '알 수 없음')})\n"
        description += f"**점수:** {score_kor}\n"

    if not description:
        description = "던담 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다."

    embed.description = description
    await interaction.followup.send(embed=embed)
