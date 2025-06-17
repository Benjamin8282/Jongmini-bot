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


# -----------------------------
# 아이템 상세 조회 + 캐시 연동
# -----------------------------

async def fetch_item_detail(session: aiohttp.ClientSession, item_id: str) -> int:
    """
    item_id로부터 장착 가능 레벨(itemAvailableLevel)을 조회.
    DB 캐시 먼저 확인, 없으면 API 호출 후 저장.
    실패 시 0 반환.
    """
    # 캐시 확인
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT item_available_level FROM item_cache WHERE item_id = ?", (item_id,))
            row = await cursor.fetchone()
            if row:
                logger.info(f"아이템 캐시에서 조회 성공: {item_id} - 레벨 {row['item_available_level']}")
                return row["item_available_level"]
    except Exception as e:
        logger.error(f"아이템 캐시 조회 중 오류: {e}")

    # 캐시에 없으면 API 호출
    url = f"{BASE_URL}/items/{item_id}"
    params = {"apikey": API_KEY}
    try:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                level = data.get("itemAvailableLevel", 0)
                logger.info(f"아이템 상세 조회 성공: {item_id} - 레벨 {level}")

                # DB에 캐시 저장
                try:
                    async with aiosqlite.connect(DB_PATH) as conn:
                        await conn.execute(
                            "INSERT OR REPLACE INTO item_cache (item_id, item_available_level) VALUES (?, ?)",
                            (item_id, level))
                        await conn.commit()
                        logger.info(f"아이템 캐시 저장 완료: {item_id} - 레벨 {level}")
                except Exception as e:
                    logger.error(f"아이템 캐시 저장 실패: {e}")

                return level
            else:
                logger.warning(f"아이템 상세 조회 실패: HTTP {response.status} - {item_id}")
    except Exception as e:
        logger.error(f"아이템 상세 조회 예외 발생: {e}")

    return 0
