# core/models.py

from discord import app_commands

SERVER_MAP = {
    "all": "전체",
    "anton": "안톤",
    "bakal": "바칼",
    "cain": "카인",
    "casillas": "카시야스",
    "diregie": "디레지에",
    "hilder": "힐더",
    "prey": "프레이",
    "siroco": "시로코"
}


SERVER_CHOICES_KR = [
    app_commands.Choice(name=kr_name, value=server_id)
    for server_id, kr_name in SERVER_MAP.items()
]

SERVER_CHOICES = [
    app_commands.Choice(name=f"{korean} ({eng})", value=eng)
    for eng, korean in SERVER_MAP.items()
]

ALLOWED_RARITIES = {"에픽", "태초"}
