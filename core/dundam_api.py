# core/dundam_api.py
import random
import time
import asyncio
from core.logger import logger

_cache = {}
_CACHE_DURATION = 60 * 10  # 10분 캐시 유지 (초 단위)


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
                                "character_id": character.get('character_id'),
                                "server_id": character.get('server_id'),
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


async def fetch_dundam_buffer_with_retry(session, character, retries=3):
    key = (character['character_id'], character['server_id'], 'buffer')

    now = time.time()
    if key in _cache:
        ts, cached_data = _cache[key]
        if now - ts < _CACHE_DURATION:
            logger.info("캐시에서 버퍼 데이터 사용: %s", character['character_name'])
            return cached_data

    url = f"https://dundam.xyz/dat/viewData.jsp?image={character['character_id']}&server={character['server_id']}"

    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    buff_cal = data.get('buffCal')
                    if not buff_cal:
                        _cache[key] = (now, None)
                        return None

                    # buffCal 마지막 항목에서 buffScore 추출
                    score_entry = buff_cal[-1]
                    buff_score_raw = score_entry.get('buffScore')
                    if not buff_score_raw:
                        _cache[key] = (now, None)
                        return None
                    buff_score = int(str(buff_score_raw).replace(',', ''))

                    result = {
                        "character_id": character.get('character_id'),
                        "server_id": character.get('server_id'),
                        "character_name": character.get('character_name'),
                        "adventure_name": character.get('adventure_name'),
                        "buff_score": buff_score
                    }
                    _cache[key] = (now, result)
                    logger.info("버퍼 데이터 조회 성공: %s - 버프스코어: %d", character['character_name'], buff_score)
                    return result

                elif response.status in (403, 429):
                    wait = (2 ** attempt) + random.random()
                    logger.warning("HTTP %d 에러: %s - %.2f초 후 재시도", response.status, character['character_name'], wait)
                    await asyncio.sleep(wait)
                else:
                    text = await response.text()
                    logger.error("HTTP %d 에러: %s - 응답: %s", response.status, character['character_name'], text)
                    return None

        except Exception as e:
            logger.error("버퍼 데이터 조회 실패: %s - %s", character['character_name'], e)
            wait = (2 ** attempt) + random.random()
            logger.info("예외 발생, %.2f초 후 재시도", wait)
            await asyncio.sleep(wait)

    logger.error("버퍼 데이터 재시도 실패: %s", character['character_name'])
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


async def fetch_all_buffers_with_rate_limit(session, characters, limit_per_second=5):
    semaphore = asyncio.Semaphore(limit_per_second)
    results = []

    async def limited_fetch(char):
        async with semaphore:
            result = await fetch_dundam_buffer_with_retry(session, char)
            await asyncio.sleep(1 / limit_per_second)
            return result

    tasks = [limited_fetch(char) for char in characters]

    for coro in asyncio.as_completed(tasks):
        res = await coro
        results.append(res)

    return results
