# core/dundam_api.py
import random
import time
import asyncio
from core.logger import logger

_cache = {}
_CACHE_DURATION = 60 * 10  # 10분 캐시 유지 (초 단위)


def _get_cached(key):
    """캐시에서 데이터 조회. 유효하면 (True, data), 아니면 (False, None)."""
    now = time.time()
    if key in _cache:
        ts, cached_data = _cache[key]
        if now - ts < _CACHE_DURATION:
            return True, cached_data
    return False, None


def _build_dundam_url(character):
    """던담 API URL 생성."""
    return (
        f"https://dundam.xyz/dat/viewData.jsp"
        f"?image={character['character_id']}&server={character['server_id']}"
    )


def _build_character_result(character, **extra_fields):
    """캐릭터 기본 정보에 추가 필드를 병합한 결과 dict 생성."""
    result = {
        "character_id": character.get('character_id'),
        "server_id": character.get('server_id'),
        "character_name": character.get('character_name'),
        "adventure_name": character.get('adventure_name'),
    }
    result.update(extra_fields)
    return result


def _extract_damage(data):
    """vsRanking에서 '총 합' 데미지 추출. 없으면 None."""
    for item in data.get('damageList', {}).get('vsRanking', []):
        if item.get('name') == '총 합':
            damage_str = item.get('dam', '0')
            return int(damage_str.replace(',', ''))
    return None


def _extract_buff_score(data):
    """buffCal에서 buffScore 추출. 없으면 None."""
    buff_cal = data.get('buffCal')
    if not buff_cal:
        return None
    score_entry = buff_cal[-1]
    buff_score_raw = score_entry.get('buffScore')
    if not buff_score_raw:
        return None
    return int(str(buff_score_raw).replace(',', ''))


async def _handle_retry_sleep(attempt):
    """재시도 전 대기 시간 계산 및 sleep."""
    wait = (2 ** attempt) + random.random()
    await asyncio.sleep(wait)
    return wait


async def _fetch_with_retry(session, character, cache_key, extractor, retries=3):
    """
    공통 던담 API 재시도 로직.
    extractor: (data, character) -> (result, log_msg) 또는 None
    """
    hit, cached = _get_cached(cache_key)
    if hit:
        logger.info("캐시에서 데이터 사용: %s", character['character_name'])
        return cached

    url = _build_dundam_url(character)
    now = time.time()

    for attempt in range(retries):
        result = await _attempt_fetch(session, url, character, cache_key, now, extractor, attempt)
        if result is not _SENTINEL_RETRY:
            return result

    logger.error("데이터 재시도 실패: %s", character['character_name'])
    return None


# 재시도를 나타내는 센티널 값
_SENTINEL_RETRY = object()


async def _attempt_fetch(session, url, character, cache_key, now, extractor, attempt):
    """단일 시도: API 호출 후 결과 추출 또는 재시도 판단."""
    try:
        async with session.get(url) as response:
            return await _handle_response(
                response, character, cache_key, now, extractor, attempt
            )
    except Exception as e:
        logger.error("데이터 조회 실패: %s - %s", character['character_name'], e)
        wait = await _handle_retry_sleep(attempt)
        logger.info("예외 발생, %.2f초 후 재시도", wait)
        return _SENTINEL_RETRY


async def _handle_response(response, character, cache_key, now, extractor, attempt):
    """HTTP 응답 상태에 따른 처리 분기."""
    if response.status == 200:
        data = await response.json(content_type=None)
        return extractor(data, character, cache_key, now)

    if response.status in (403, 429):
        wait = await _handle_retry_sleep(attempt)
        logger.warning(
            "HTTP %d 에러: %s - %.2f초 후 재시도",
            response.status, character['character_name'], wait
        )
        return _SENTINEL_RETRY

    text = await response.text()
    logger.error("HTTP %d 에러: %s - 응답: %s", response.status, character['character_name'], text)
    return None


def _damage_extractor(data, character, cache_key, now):
    """딜러 데미지 데이터 추출기."""
    damage = _extract_damage(data)
    if damage is None:
        logger.warning("총 합 항목 없음: %s", character['character_name'])
        return None
    result = _build_character_result(character, damage=damage)
    _cache[cache_key] = (now, result)
    logger.info("던담 데이터 조회 성공: %s - 데미지: %d", character['character_name'], damage)
    return result


def _buffer_extractor(data, character, cache_key, now):
    """버퍼 스코어 데이터 추출기."""
    buff_score = _extract_buff_score(data)
    if buff_score is None:
        _cache[cache_key] = (now, None)
        return None
    result = _build_character_result(character, buff_score=buff_score)
    _cache[cache_key] = (now, result)
    logger.info("버퍼 데이터 조회 성공: %s - 버프스코어: %d", character['character_name'], buff_score)
    return result


async def fetch_dundam_data_with_retry(session, character, retries=3):
    key = (character['character_id'], character['server_id'])
    return await _fetch_with_retry(session, character, key, _damage_extractor, retries)


async def fetch_dundam_buffer_with_retry(session, character, retries=3):
    key = (character['character_id'], character['server_id'], 'buffer')
    return await _fetch_with_retry(session, character, key, _buffer_extractor, retries)


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
