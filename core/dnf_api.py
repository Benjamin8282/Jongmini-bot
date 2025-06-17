# core/dnf_api.py

import os
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
        return response.json()
    return None

def get_character_image_url(server_id: str, character_id: str, zoom: int = 1):
    return f"https://img-api.neople.co.kr/df/servers/{server_id}/characters/{character_id}?zoom={zoom}"
