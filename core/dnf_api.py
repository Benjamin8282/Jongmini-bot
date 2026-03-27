import os
from core.logger import logger

import aiohttp
from dotenv import load_dotenv

from datetime import datetime

from core.db import get_conn

load_dotenv()

# 필수 환경 변수 검증
API_KEY = os.getenv("NEOPLE_API_KEY")
if not API_KEY:
    raise ValueError("NEOPLE_API_KEY 환경 변수가 설정되지 않았습니다.")

BASE_URL = "https://api.neople.co.kr/df"

# 글로벌 메모리 캐시
ITEM_DETAIL_MEMCACHE = {}

# 공유 HTTP 세션
_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    """공유 HTTP 세션 반환. 최초 호출 시 생성."""
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        _session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return _session


async def close_session():
    """봇 종료 시 HTTP 세션 정리."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def search_characters(server_id: str, character_name: str):
    logger.info(f"search_characters 호출: server_id={server_id}, character_name={character_name}")
    url = f"{BASE_URL}/servers/{server_id}/characters"
    params = {
        "characterName": character_name,
        "apikey": API_KEY
    }

    try:
        session = await get_session()
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                logger.info(f"search_characters 성공: {len(data.get('rows', []))}개 캐릭터 반환")
                return data
            else:
                logger.warning(f"search_characters 실패: HTTP {response.status}")
    except Exception as e:
        logger.error(f"search_characters 예외 발생: {e}")

    return None


def get_character_image_url(server_id: str, character_id: str, zoom: int = 1):
    url = f"https://img-api.neople.co.kr/df/servers/{server_id}/characters/{character_id}?zoom={zoom}"
    logger.info(f"get_character_image_url 호출: {url}")
    return url


async def get_character_image_bytes(server_id: str, character_id: str):
    logger.info(f"get_character_image_bytes 호출: server_id={server_id}, character_id={character_id}")
    zoom = 3
    url = f"https://img-api.neople.co.kr/df/servers/{server_id}/characters/{character_id}?zoom={zoom}"

    try:
        session = await get_session()
        async with session.get(url) as response:
            if response.status == 200:
                img_bytes = await response.read()
                logger.info(f"get_character_image_bytes 성공: {len(img_bytes)} 바이트 수신")
                return img_bytes
            else:
                logger.warning(f"get_character_image_bytes 실패: HTTP {response.status}")
    except Exception as e:
        logger.error(f"get_character_image_bytes 예외 발생: {e}")

    return None


async def get_character_details(server_id: str, character_id: str) -> dict:
    logger.info(f"get_character_details 호출: server_id={server_id}, character_id={character_id}")
    url = f"{BASE_URL}/servers/{server_id}/characters/{character_id}"
    params = {"apikey": API_KEY}

    try:
        session = await get_session()
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                logger.info("get_character_details 성공")
                return data
            else:
                logger.warning(f"get_character_details 실패: HTTP {response.status}")
    except Exception as e:
        logger.error(f"get_character_details 예외 발생: {e}")

    return {}


async def fetch_timeline(server_id: str, character_id: str, start_date: str = None, end_date: str = None):
    url = f"{BASE_URL}/servers/{server_id}/characters/{character_id}/timeline"

    # 기본값: 최근 30일 (또는 원하는 범위로)
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%dT%H%M")
    if start_date is None:
        # 기본 30일 전
        from datetime import timedelta
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%dT%H%M")

    params = {
        "apikey": API_KEY,
        "startDate": start_date,
        "endDate": end_date,
        "code": "505,504,507,508,513,550,551,552,553,554,555,556",
        "limit": 100
    }

    session = await get_session()
    async with session.get(url, params=params) as resp:
        if resp.status == 200:
            return await resp.json()
        else:
            return None


def _build_timeline_params(start_date: str | None, end_date: str | None) -> dict:
    """타임라인 API 파라미터 구성 (기본값 적용)."""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%dT%H%M")
    if start_date is None:
        from datetime import timedelta
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%dT%H%M")

    return {
        "apikey": API_KEY,
        "startDate": start_date,
        "endDate": end_date,
        "code": "505,504,507,508,513,550,551,552,553,554,555,556",
        "limit": 100
    }


async def _fetch_single_timeline_page(session, url, params, next_token):
    """타임라인 단일 페이지 조회. (rows, next_token) 또는 실패 시 None 반환."""
    if next_token:
        params["next"] = next_token
    else:
        params.pop("next", None)

    async with session.get(url, params=params) as resp:
        logger.info(f"fetch_timeline_with_pagination 호출: {url} - next_token={next_token}")
        logger.info(f"응답 상태: {resp.status}")
        if resp.status != 200:
            data = await resp.text()  # json이 아닐 수도 있으니 텍스트로 먼저 찍기
            logger.warning(f"API 호출 실패 응답 내용: {data}")
            return None

        data = await resp.json()
        timeline = data.get("timeline", {})
        rows = timeline.get("rows", [])
        new_next = timeline.get("next")
        return rows, new_next


async def fetch_timeline_with_pagination(
    server_id: str, character_id: str, start_date: str = None, end_date: str = None
):
    url = f"{BASE_URL}/servers/{server_id}/characters/{character_id}/timeline"
    params = _build_timeline_params(start_date, end_date)

    all_rows = []
    next_token = None

    session = await get_session()
    while True:
        page_result = await _fetch_single_timeline_page(session, url, params, next_token)
        if page_result is None:
            return None
        rows, next_token = page_result
        all_rows.extend(rows)
        if not next_token:
            break

    return {"timeline": {"rows": all_rows}}


# ===============================
# 메모리 캐시 프리로드 함수
# ===============================
async def preload_item_cache():
    """
    부팅 시 DB의 item_cache 전체를 메모리 캐시에 올림
    """
    global ITEM_DETAIL_MEMCACHE
    ITEM_DETAIL_MEMCACHE = {}
    try:
        conn = await get_conn()
        async with conn.execute("SELECT item_id, item_available_level FROM item_cache") as cursor:
            async for row in cursor:
                ITEM_DETAIL_MEMCACHE[row[0]] = row[1]
        logger.info(f"메모리 캐시 preload 완료: {len(ITEM_DETAIL_MEMCACHE)}개 아이템")
    except Exception as e:
        logger.error(f"메모리 캐시 preload 실패: {e}")

# ===============================
# 아이템 상세 정보 조회 (캐싱 포함)
# ===============================


async def _fetch_item_from_db(item_id: str) -> int | None:
    """DB 캐시에서 아이템 레벨 조회. 없으면 None."""
    try:
        conn = await get_conn()
        cursor = await conn.execute(
            "SELECT item_available_level FROM item_cache WHERE item_id = ?", (item_id,))
        row = await cursor.fetchone()
        if row:
            level = row[0]
            ITEM_DETAIL_MEMCACHE[item_id] = level  # 메모리 캐시 동기화
            logger.info(f"[dbcache] 캐시 히트: {item_id} - {level}")
            return level
    except Exception as e:
        logger.error(f"DB 캐시 조회 중 오류: {e}")
    return None


async def _save_item_to_db(item_id: str, level: int):
    """아이템 레벨을 DB 캐시에 저장."""
    try:
        conn = await get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO item_cache (item_id, item_available_level) VALUES (?, ?)",
            (item_id, level)
        )
        await conn.commit()
        logger.info(f"아이템 캐시 저장 완료: {item_id} - 레벨 {level}")
    except Exception as e:
        logger.error(f"아이템 캐시 저장 실패: {e}")


async def _fetch_item_from_api(item_id: str) -> int | None:
    """API에서 아이템 레벨 조회. 성공 시 메모리/DB에 캐싱."""
    url = f"{BASE_URL}/items/{item_id}"
    params = {"apikey": API_KEY}
    try:
        session = await get_session()
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                level = data.get("itemAvailableLevel", 0)
                logger.info(f"아이템 상세 조회 성공: {item_id} - 레벨 {level}")
                ITEM_DETAIL_MEMCACHE[item_id] = level
                await _save_item_to_db(item_id, level)
                return level
            else:
                logger.warning(f"아이템 상세 조회 실패: HTTP {response.status} - {item_id}")
    except Exception as e:
        logger.error(f"아이템 상세 조회 예외 발생: {e}")
    return None


async def fetch_item_detail(item_id: str) -> int:
    """
    1. 메모리 캐시 → 2. DB → 3. API 순서로 조회, 없으면 0 반환
    API 조회 성공 시 메모리/DB에 모두 저장
    """
    # 1. 메모리 캐시 조회
    if item_id in ITEM_DETAIL_MEMCACHE:
        logger.info(f"[memcache] 캐시 히트: {item_id} - {ITEM_DETAIL_MEMCACHE[item_id]}")
        return ITEM_DETAIL_MEMCACHE[item_id]

    # 2. DB 캐시 조회
    db_result = await _fetch_item_from_db(item_id)
    if db_result is not None:
        return db_result

    # 3. API 조회
    api_result = await _fetch_item_from_api(item_id)
    if api_result is not None:
        return api_result

    return 0


# ===============================
# 경매장 시세 API
# ===============================

async def fetch_auction_sold(item_name: str) -> list[dict] | None:
    """경매장 거래 시세 조회 (/df/auction-sold)"""
    url = f"{BASE_URL}/auction-sold"
    params = {
        "itemName": item_name,
        "limit": 400,
        "apikey": API_KEY
    }
    try:
        session = await get_session()
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                rows = data.get("rows", [])
                logger.info(f"경매장 시세 조회 성공: {item_name} - {len(rows)}건")
                return rows
            else:
                logger.warning(f"경매장 시세 조회 실패: HTTP {response.status}")
    except Exception as e:
        logger.error(f"경매장 시세 조회 예외: {e}")
    return None


async def fetch_item_search(item_name: str) -> list[dict] | None:
    """아이템 이름으로 검색 (/df/items)"""
    url = f"{BASE_URL}/items"
    params = {
        "itemName": item_name,
        "wordType": "full",
        "limit": 30,
        "apikey": API_KEY
    }
    try:
        session = await get_session()
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                rows = data.get("rows", [])
                logger.info(f"아이템 검색 성공: {item_name} - {len(rows)}건")
                return rows
            else:
                logger.warning(f"아이템 검색 실패: HTTP {response.status}")
    except Exception as e:
        logger.error(f"아이템 검색 예외: {e}")
    return None
