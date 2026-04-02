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

# 일반 아이템 등급별 가중치
RARITY_WEIGHTS = {
    "태초": 25,
    "에픽": 2,
    "레전더리": 1
}

# 서약 장비(code 550~556) 등급별 가중치
COVENANT_RARITY_WEIGHTS = {
    "태초": 100,
    "에픽": 10,
    "레전더리": 4
}

COVENANT_CODES = {550, 551, 552, 553, 554, 555, 556, 557}

ENHANCE_CODES = {401, 402}  # 아이템 강화/증폭
SEALED_LOCK_CODES = {501}   # 봉인된 자물쇠 아이템 획득

MAX_MIST_LEVEL = 100


def format_score_korean(num: int) -> str:
    """숫자를 한국식 단위(조/억/만)로 포맷. 조 단위에서는 억까지만 표시."""
    if num >= 1_000_000_000_000:
        조 = num // 1_000_000_000_000
        억 = (num % 1_000_000_000_000) // 100_000_000
        if 억 > 0:
            return f"{조}조 {억}억"
        return f"{조}조"
    elif num >= 100_000_000:
        억 = num // 100_000_000
        만 = (num % 100_000_000) // 10_000
        if 만 > 0:
            return f"{억}억 {만}만"
        return f"{억}억"
    elif num >= 10_000:
        만 = num // 10_000
        나머지 = num % 10_000
        if 나머지 > 0:
            return f"{만}만 {나머지}"
        return f"{만}만"
    else:
        return f"{num}"


def parse_exp_rate(exp_rate: str) -> float:
    """'45%' -> 45.0, 파싱 실패 시 0.0"""
    try:
        return float(exp_rate.replace("%", ""))
    except (ValueError, AttributeError):
        return 0.0
