# core/dnf_api.py

import os
from io import BytesIO

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NEOPLE_API_KEY")

BASE_URL = "https://api.neople.co.kr/df"

def search_characters(server_id: str, character_name: str):
    url = f"{BASE_URL}/servers/{server_id}/characters"
    params = {
        "characterName": character_name,
        "apikey": API_KEY
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        print(response.json())
        return response.json()
    return None

def get_character_image_url(server_id: str, character_id: str, zoom: int = 1):
    return f"https://img-api.neople.co.kr/df/servers/{server_id}/characters/{character_id}?zoom={zoom}"


def get_character_image_bytes(server_id: str, character_id: str) -> BytesIO:
    """
    캐릭터 이미지를 바이트 형태로 반환 (Discord 파일 전송용)
    """
    zoom = 3  # 기본 사이즈
    url = f"https://img-api.neople.co.kr/df/servers/{server_id}/characters/{character_id}?zoom={zoom}"
    response = requests.get(url)
    response.raise_for_status()
    return BytesIO(response.content)

def get_character_details(server_id: str, character_id: str) -> dict:
    """
    특정 서버와 캐릭터 ID에 대한 캐릭터 정보를 가져옵니다.
    :param server_id:
    :param character_id:
    :return:
    """
    url = f"{BASE_URL}/servers/{server_id}/characters/{character_id}"
    params = {"apikey": API_KEY}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    return {}
