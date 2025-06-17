import asyncio

import aiohttp

from core import dnf_api
from core.db import get_all_characters_grouped_by_adventure
from core.db import init_db


async def filter_valid_items(timeline_rows, session):
    valid_items = []
    for row in timeline_rows:
        item_id = row.get("data", {}).get("itemId")
        if not item_id:
            continue
        equip_level = await dnf_api.fetch_item_detail(item_id)
        if equip_level == 115:  # 장착 가능 레벨 조건
            valid_items.append(row)
    return valid_items


async def main():
    grouped = await get_all_characters_grouped_by_adventure()
    if not grouped:
        print("DB에 등록된 캐릭터가 없습니다.")
        return

    first_adventure = next(iter(grouped))
    characters = grouped[first_adventure]
    if not characters:
        print("선택한 모험단에 캐릭터가 없습니다.")
        return

    char = characters[0]
    print(f"조회할 캐릭터: {char['character_name']} ({char['character_id']}) 서버: {char['server_id']}")

    timeline = await dnf_api.fetch_timeline(char['server_id'], char['character_id'])
    if timeline is None or "timeline" not in timeline or "rows" not in timeline["timeline"]:
        print("타임라인 데이터를 받아오지 못했습니다.")
        return

    async with aiohttp.ClientSession() as session:
        filtered_items = await filter_valid_items(timeline["timeline"]["rows"], session)

    print(f"장착 가능 레벨 115 아이템 {len(filtered_items)}개:")
    for item in filtered_items:
        print(item)


if __name__ == "__main__":
    asyncio.run(init_db())
    asyncio.run(dnf_api.preload_item_cache())
    asyncio.run(main())