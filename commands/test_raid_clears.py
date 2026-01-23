from discord import app_commands, Interaction
from core.db import get_all_characters
from core.dnf_api import fetch_raid_clears
from core.logger import logger
import json


@app_commands.command(name="레이드테스트", description="레이드 클리어 정보 조회 테스트 (개발용)")
async def test_raid_clears(interaction: Interaction):
    """레이드 클리어 API 응답 구조 확인용 테스트 커맨드"""
    await interaction.response.defer(thinking=True)

    # 등록된 캐릭터 조회
    characters = await get_all_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    # 첫 번째 캐릭터로 테스트 (최대 3개)
    test_characters = characters[:3]

    results_text = "**레이드 클리어 정보 테스트 결과**\n\n"

    for char in test_characters:
        character_name = char['character_name']
        server_id = char['server_id']
        character_id = char['character_id']

        logger.info(f"레이드 클리어 조회: {character_name} ({character_id})")

        # 레이드 클리어 정보 조회
        raid_data = await fetch_raid_clears(server_id, character_id)

        # JSON 응답 전체를 로그로 출력
        logger.info(f"[{character_name}] 레이드 클리어 API 응답:")
        logger.info(json.dumps(raid_data, ensure_ascii=False, indent=2))

        results_text += f"**캐릭터**: {character_name}\n"

        if raid_data and "timeline" in raid_data:
            rows = raid_data.get("timeline", {}).get("rows", [])
            results_text += f"**레이드 클리어 수**: {len(rows)}개\n"

            if rows:
                # 첫 번째 레이드 클리어 정보만 표시
                first_clear = rows[0]
                results_text += "```json\n"
                results_text += json.dumps(first_clear, ensure_ascii=False, indent=2)
                results_text += "\n```\n"
            else:
                results_text += "레이드 클리어 기록이 없습니다.\n"
        else:
            results_text += "API 조회 실패 또는 데이터 없음\n"

        results_text += "\n---\n\n"

    # Discord 메시지 길이 제한 (2000자)
    if len(results_text) > 1900:
        results_text = results_text[:1900] + "\n... (결과가 너무 길어 생략)"

    await interaction.followup.send(results_text)
    logger.info("레이드 테스트 커맨드 실행 완료")
