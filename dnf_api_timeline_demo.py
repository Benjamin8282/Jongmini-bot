import asyncio
import aiohttp
from core.db import get_all_characters_grouped_by_adventure
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NEOPLE_API_KEY")
BASE_URL = "https://api.neople.co.kr/df"
ITEM_DETAIL_CACHE = {}  # itemId별 장착 가능 레벨 캐시

async def fetch_timeline(server_id: str, character_id: str):
    url = f"{BASE_URL}/servers/{server_id}/characters/{character_id}/timeline"

    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%dT%H%M")
    end_date = datetime.now().strftime("%Y%m%dT%H%M")

    params = {
        "apikey": API_KEY,
        "startDate": start_date,
        "endDate": end_date,
        "code": "505,504,507,508,513",
        "limit": 100
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            print(f"API 호출 상태 코드: {resp.status}")
            data = await resp.json()
            if resp.status == 200:
                return data
            else:
                print(f"API 호출 실패: HTTP {resp.status}")
                return None

async def fetch_item_detail(session: aiohttp.ClientSession, item_id: str):
    if item_id in ITEM_DETAIL_CACHE:
        return ITEM_DETAIL_CACHE[item_id]

    url = f"{BASE_URL}/items/{item_id}"
    params = {"apikey": API_KEY}

    async with session.get(url, params=params) as resp:
        if resp.status == 200:
            data = await resp.json()
            equip_level = data.get("itemAvailableLevel", 0)
            ITEM_DETAIL_CACHE[item_id] = equip_level
            return equip_level
        else:
            print(f"아이템 상세 조회 실패: HTTP {resp.status} - {item_id}")
            ITEM_DETAIL_CACHE[item_id] = 0
            return 0

async def filter_valid_items(timeline_rows, session):
    valid_items = []
    for row in timeline_rows:
        item_id = row.get("data", {}).get("itemId")
        if not item_id:
            continue
        equip_level = await fetch_item_detail(session, item_id)
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

    timeline = await fetch_timeline(char['server_id'], char['character_id'])
    if timeline is None or "timeline" not in timeline or "rows" not in timeline["timeline"]:
        print("타임라인 데이터를 받아오지 못했습니다.")
        return

    async with aiohttp.ClientSession() as session:
        filtered_items = await filter_valid_items(timeline["timeline"]["rows"], session)

    print(f"장착 가능 레벨 115 아이템 {len(filtered_items)}개:")
    for item in filtered_items:
        print(item)

if __name__ == "__main__":
    asyncio.run(main())
