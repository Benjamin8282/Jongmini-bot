# core/dnf_api.py

import os

import aiohttp
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NEOPLE_API_KEY")

BASE_URL = "https://api.neople.co.kr/df"


async def search_characters(server_id: str, character_name: str):
    url = f"{BASE_URL}/servers/{server_id}/characters"
    params = {
        "characterName": character_name,
        "apikey": API_KEY
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                return await response.json()
    return None


def get_character_image_url(server_id: str, character_id: str, zoom: int = 1):
    return f"https://img-api.neople.co.kr/df/servers/{server_id}/characters/{character_id}?zoom={zoom}"


async def get_character_image_bytes(server_id: str, character_id: str):
    zoom = 3
    url = f"https://img-api.neople.co.kr/df/servers/{server_id}/characters/{character_id}?zoom={zoom}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
            else:
                return None


async def get_character_details(server_id: str, character_id: str) -> dict:
    """
    특정 서버와 캐릭터 ID에 대한 캐릭터 정보를 가져옵니다.
    :param server_id:
    :param character_id:
    :return:
    """
    url = f"{BASE_URL}/servers/{server_id}/characters/{character_id}"
    params = {"apikey": API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                return await response.json()
    return {}
