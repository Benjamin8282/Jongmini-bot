# core/models.py

from discord import app_commands

SERVER_MAP = {
    "anton": "안톤",
    "bakal": "바칼",
    "cain": "카인",
    "casillas": "카시야스",
    "diregie": "디레지에",
    "hilder": "힐더",
    "prey": "프레이",
    "siroco": "시로코"
}

SERVER_CHOICES = [
    app_commands.Choice(name=f"{korean} ({eng})", value=eng)
    for eng, korean in SERVER_MAP.items()
]
