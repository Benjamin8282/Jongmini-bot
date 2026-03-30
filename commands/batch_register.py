import asyncio

import discord
from discord import app_commands, Interaction

from core.dnf_api import search_characters, get_character_details
from core.db import save_character, register_character
from core.models import SERVER_CHOICES_KR, SERVER_MAP
from core.logger import logger

_API_SEMAPHORE = asyncio.Semaphore(5)


async def _register_one(server_id: str, name: str, user_id: int) -> str:
    """단일 캐릭터 검색 및 등록. 결과 메시지 문자열 반환."""
    async with _API_SEMAPHORE:
        result = await search_characters(server_id, name)

    if not result or not result.get("rows"):
        return f"❌ {name} - 검색 결과 없음"

    char = result["rows"][0]

    async with _API_SEMAPHORE:
        details = await get_character_details(server_id, char["characterId"])

    adventure_name = details.get("adventureName", "알 수 없음") if details else "알 수 없음"
    char["adventureName"] = adventure_name

    await save_character(char)
    is_new = await register_character(user_id, char["characterId"])

    info = f"{char['characterName']} - {char['jobName']}/{char['jobGrowName']} (Lv.{char['level']}) [{adventure_name}]"
    if not is_new:
        return f"⏭️ {info} - 이미 등록됨"
    return f"✅ {info}"


@app_commands.command(name="일괄등록", description="여러 캐릭터를 한번에 등록합니다 (쉼표로 구분)")
@app_commands.describe(server="서버를 선택하세요", characters="캐릭터 이름 (쉼표로 구분)")
@app_commands.choices(server=SERVER_CHOICES_KR)
async def batch_register(interaction: Interaction, server: app_commands.Choice[str], characters: str):
    logger.info(f"/일괄등록 호출: 사용자={interaction.user.id}, 서버={server.value}, 캐릭터={characters}")
    await interaction.response.defer(thinking=True)

    names = [n.strip() for n in characters.split(",") if n.strip()]
    if not names:
        await interaction.followup.send("등록할 캐릭터 이름을 입력해주세요.")
        return

    server_name = SERVER_MAP.get(server.value, server.value)
    tasks = [_register_one(server.value, name, interaction.user.id) for name in names]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    lines = []
    success = 0
    for r in results:
        if isinstance(r, Exception):
            lines.append(f"❌ 처리 중 오류 발생")
            logger.error(f"일괄등록 오류: {r}")
        else:
            lines.append(r)
            if r.startswith("✅"):
                success += 1

    embed = discord.Embed(
        title=f"일괄 등록 완료 ({success}/{len(names)} 성공)",
        description="\n".join(lines),
        color=0x2ECC71 if success == len(names) else 0xF39C12
    )
    embed.set_footer(text=f"서버: {server_name}")
    await interaction.followup.send(embed=embed)
