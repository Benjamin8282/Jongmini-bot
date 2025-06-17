import os
from core.logger import logger

import aiohttp
from dotenv import load_dotenv
import aiosqlite
from pathlib import Path

load_dotenv()
API_KEY = os.getenv("NEOPLE_API_KEY")

BASE_URL = "https://api.neople.co.kr/df"
DB_PATH = Path("data/characters.db")

# 글로벌 메모리 캐시
ITEM_DETAIL_MEMCACHE = {}


async def search_characters(server_id: str, character_name: str):
    logger.info(f"search_characters 호출: server_id={server_id}, character_name={character_name}")
    url = f"{BASE_URL}/servers/{server_id}/characters"
    params = {
        "characterName": character_name,
        "apikey": API_KEY
    }

    try:
        async with aiohttp.ClientSession() as session:
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
        async with aiohttp.ClientSession() as session:
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
        async with aiohttp.ClientSession() as session:
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


async def fetch_timeline(server_id: str, character_id: str):
    url = f"{BASE_URL}/servers/{server_id}/characters/{character_id}/timeline"

    # 날짜 범위는 필요에 따라 수정 가능
    params = {
        "apikey": API_KEY,
        "startDate": "",  # 필요 시 지정
        "endDate": "",    # 필요 시 지정
        "code": "505,504,507,508,513",
        "limit": 100
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                return None


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
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute("SELECT item_id, item_available_level FROM item_cache") as cursor:
                async for row in cursor:
                    ITEM_DETAIL_MEMCACHE[row[0]] = row[1]
        logger.info(f"메모리 캐시 preload 완료: {len(ITEM_DETAIL_MEMCACHE)}개 아이템")
    except Exception as e:
        logger.error(f"메모리 캐시 preload 실패: {e}")

# ===============================
# 아이템 상세 정보 조회 (캐싱 포함)
# ===============================
async def fetch_item_detail(item_id: str) -> int:
    """
    1. 메모리 캐시 → 2. DB → 3. API 순서로 조회, 없으면 0 반환
    API 조회 성공 시 메모리/DB에 모두 저장
    """
    # 1. 메모리 캐시 조회
    if item_id in ITEM_DETAIL_MEMCACHE:
        logger.info(f"[memcache] 캐시 히트: {item_id} - {ITEM_DETAIL_MEMCACHE[item_id]}")
        return ITEM_DETAIL_MEMCACHE[item_id]

    # 2. DB 캐시 조회 (동기화 누락/실패 대응용)
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
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

    # 3. API 조회
    url = f"{BASE_URL}/items/{item_id}"
    params = {"apikey": API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    level = data.get("itemAvailableLevel", 0)
                    logger.info(f"아이템 상세 조회 성공: {item_id} - 레벨 {level}")
                    # 메모리/DB 동시 캐싱
                    ITEM_DETAIL_MEMCACHE[item_id] = level
                    try:
                        async with aiosqlite.connect(DB_PATH) as conn2:
                            await conn2.execute(
                                "INSERT OR REPLACE INTO item_cache (item_id, item_available_level) VALUES (?, ?)",
                                (item_id, level)
                            )
                            await conn2.commit()
                        logger.info(f"아이템 캐시 저장 완료: {item_id} - 레벨 {level}")
                    except Exception as e:
                        logger.error(f"아이템 캐시 저장 실패: {e}")
                    return level
                else:
                    logger.warning(f"아이템 상세 조회 실패: HTTP {response.status} - {item_id}")
    except Exception as e:
        logger.error(f"아이템 상세 조회 예외 발생: {e}")

    return 0
