import asyncio

from core import dnf_api
from core.db import get_all_characters_grouped_by_adventure
from core.db import init_db


async def main():
    grouped = await get_all_characters_grouped_by_adventure()
    if not grouped:
        print("DB에 등록된 캐릭터가 없습니다.")
        return

    # "김시웅" 캐릭터 찾기
    target_char = None
    for adventure, characters in grouped.items():
        for char in characters:
            if char['character_name'] == "김시웅":
                target_char = char
                break
        if target_char:
            break

    if not target_char:
        print("김시웅 캐릭터를 찾을 수 없습니다.")
        return

    print(f"조회할 캐릭터: {target_char['character_name']} ({target_char['character_id']}) 서버: {target_char['server_id']}")

    timeline = await dnf_api.fetch_timeline(target_char['server_id'], target_char['character_id'])
    if timeline is None or "timeline" not in timeline or "rows" not in timeline["timeline"]:
        print("타임라인 데이터를 받아오지 못했습니다.")
        return

    # 아이템 필터링 없이 전체 rows 출력
    print(f"총 타임라인 이벤트 수: {len(timeline['timeline']['rows'])}")
    for row in timeline['timeline']['rows']:
        print(row)


if __name__ == "__main__":
    asyncio.run(init_db())
    asyncio.run(dnf_api.preload_item_cache())
    asyncio.run(main())
