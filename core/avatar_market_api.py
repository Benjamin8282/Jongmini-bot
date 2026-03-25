import os
import time

from dotenv import load_dotenv

from core.dnf_api import get_session
from core.logger import logger

load_dotenv()
API_KEY = os.getenv("NEOPLE_API_KEY")
BASE_URL = "https://api.neople.co.kr/df"

# 모듈 레벨 캐시
_hashtag_cache = {"data": [], "time": 0}
_jobs_cache = {"data": [], "time": 0}

_HASHTAG_CACHE_DURATION = 3600      # 1시간
_JOBS_CACHE_DURATION = 86400        # 24시간


def _is_cache_valid(cache: dict, duration: int) -> bool:
    """캐시 유효성 검사."""
    return bool(cache["data"]) and (time.time() - cache["time"] < duration)


async def _fetch_json(url: str, params: dict) -> dict | None:
    """공통 GET 요청 후 JSON 반환. 실패 시 None."""
    try:
        session = await get_session()
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.warning(f"아바타 마켓 API 실패: HTTP {resp.status} - {url}")
    except Exception as e:
        logger.error(f"아바타 마켓 API 예외: {e} - {url}")
    return None


_OPTIONAL_PARAMS = {
    "title": "title",
    "job_id": "jobId",
    "hashtag": "hashtag",
    "avatar_rarity": "avatarRarity",
    "slot_id": "slotId",
}


def _build_params(limit, **kwargs):
    """검색 파라미터 구성. None이 아닌 값만 포함."""
    params = {"apikey": API_KEY, "limit": limit}
    for key, api_key in _OPTIONAL_PARAMS.items():
        val = kwargs.get(key)
        if val:
            params[api_key] = val
    return params


async def fetch_avatar_sale(
    title=None, job_id=None, hashtag=None,
    avatar_rarity=None, slot_id=None, limit=20,
) -> list[dict]:
    """아바타 마켓 판매 중인 상품 검색."""
    url = f"{BASE_URL}/avatar-market/sale"
    params = _build_params(
        limit, title=title, job_id=job_id, hashtag=hashtag,
        avatar_rarity=avatar_rarity, slot_id=slot_id,
    )
    data = await _fetch_json(url, params)
    if data is None:
        return []
    rows = data.get("rows", [])
    logger.info(f"아바타 마켓 판매 검색 완료: {len(rows)}건")
    return rows


async def fetch_avatar_sold(
    title=None, job_id=None, hashtag=None,
    avatar_rarity=None, slot_id=None, limit=50,
) -> list[dict]:
    """아바타 마켓 시세(판매 완료) 검색."""
    url = f"{BASE_URL}/avatar-market/sold"
    params = _build_params(
        limit, title=title, job_id=job_id, hashtag=hashtag,
        avatar_rarity=avatar_rarity, slot_id=slot_id,
    )
    data = await _fetch_json(url, params)
    if data is None:
        return []
    rows = data.get("rows", [])
    logger.info(f"아바타 마켓 시세 검색 완료: {len(rows)}건")
    return rows


async def fetch_avatar_hashtags() -> list[str]:
    """아바타 마켓 해시태그 목록 조회 (1시간 캐시)."""
    if _is_cache_valid(_hashtag_cache, _HASHTAG_CACHE_DURATION):
        return _hashtag_cache["data"]

    url = f"{BASE_URL}/avatar-market/hashtag"
    params = {"apikey": API_KEY}
    data = await _fetch_json(url, params)
    if data is None:
        return _hashtag_cache["data"]

    rows = data.get("rows", [])
    _hashtag_cache["data"] = rows
    _hashtag_cache["time"] = time.time()
    logger.info(f"아바타 해시태그 캐시 갱신: {len(rows)}개")
    return rows


def _flatten_jobs(raw_rows: list[dict]) -> list[dict]:
    """직업 API 응답에서 (jobId, jobName) 리스트로 평탄화."""
    result = []
    for job in raw_rows:
        result.append({"jobId": job["jobId"], "jobName": job["jobName"]})
    return result


async def fetch_jobs() -> list[dict]:
    """직업 목록 조회 (24시간 캐시). [{jobId, jobName}, ...]."""
    if _is_cache_valid(_jobs_cache, _JOBS_CACHE_DURATION):
        return _jobs_cache["data"]

    url = f"{BASE_URL}/jobs"
    params = {"apikey": API_KEY}
    data = await _fetch_json(url, params)
    if data is None:
        return _jobs_cache["data"]

    raw_rows = data.get("rows", [])
    jobs = _flatten_jobs(raw_rows)
    _jobs_cache["data"] = jobs
    _jobs_cache["time"] = time.time()
    logger.info(f"직업 캐시 갱신: {len(jobs)}개")
    return jobs


async def preload_caches():
    """봇 부팅 시 해시태그/직업 캐시 워밍."""
    logger.info("아바타 마켓 캐시 프리로드 시작")
    await fetch_avatar_hashtags()
    await fetch_jobs()
    logger.info("아바타 마켓 캐시 프리로드 완료")
