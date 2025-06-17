import os
from core.logger import logger

import aiohttp
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NEOPLE_API_KEY")

BASE_URL = "https://api.neople.co.kr/df"


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
