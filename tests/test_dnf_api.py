"""
core/dnf_api.py 실제 API 통합 테스트.

네오플 DNF 오픈 API를 직접 호출하여 응답 형식과 동작을 검증한다.
NEOPLE_API_KEY 환경변수가 설정되어 있어야 실행되며,
CI 환경에서는 자동으로 스킵된다.
"""
import os

import pytest

# NEOPLE_API_KEY 미설정 시 모듈 전체 스킵
pytestmark = [
    pytest.mark.skipif(
        not os.getenv("NEOPLE_API_KEY"),
        reason="NEOPLE_API_KEY not set",
    ),
    pytest.mark.asyncio,
]

from core.dnf_api import (  # noqa: E402
    search_characters,
    get_character_details,
    get_character_image_url,
    fetch_item_detail,
    fetch_timeline,
)


# ─── 검색 테스트 ───


async def test_search_characters_returns_rows():
    """캐릭터 검색 결과에 rows 키가 있고 1개 이상의 결과를 반환해야 한다."""
    result = await search_characters("casillas", "김철완")

    # API 장애 시 None 반환 허용
    if result is None:
        pytest.skip("DNF API가 응답하지 않음")

    assert isinstance(result, dict), "반환값은 dict여야 한다"
    assert "rows" in result, "rows 키가 존재해야 한다"
    assert isinstance(result["rows"], list), "rows는 list여야 한다"
    assert len(result["rows"]) > 0, "검색 결과가 1개 이상이어야 한다"


async def test_search_characters_row_has_expected_keys():
    """검색 결과의 각 row에 characterId, characterName 등 필수 키가 있어야 한다."""
    result = await search_characters("casillas", "김철완")

    if result is None:
        pytest.skip("DNF API가 응답하지 않음")

    row = result["rows"][0]
    assert "characterId" in row, "characterId 키 필수"
    assert "characterName" in row, "characterName 키 필수"
    assert "serverId" in row, "serverId 키 필수"


# ─── 캐릭터 상세 테스트 ───


async def test_get_character_details():
    """실제 캐릭터 ID로 상세 정보를 조회하면 characterName이 포함된 dict를 반환해야 한다."""
    # 먼저 검색으로 유효한 캐릭터 ID 획득
    search = await search_characters("casillas", "김철완")
    if search is None or not search.get("rows"):
        pytest.skip("캐릭터 검색 실패 - 상세 조회 테스트 스킵")

    row = search["rows"][0]
    server_id = row["serverId"]
    character_id = row["characterId"]

    result = await get_character_details(server_id, character_id)

    # API 장애 시 빈 dict 반환
    if not result:
        pytest.skip("캐릭터 상세 API가 응답하지 않음")

    assert isinstance(result, dict), "반환값은 dict여야 한다"
    assert "characterName" in result, "characterName 키가 존재해야 한다"
    assert isinstance(result["characterName"], str), "characterName은 문자열이어야 한다"


# ─── 캐릭터 이미지 URL 테스트 ───


async def test_get_character_image_url():
    """이미지 URL이 img-api.neople.co.kr 도메인을 포함해야 한다."""
    # get_character_image_url은 동기 함수 (API 호출 없이 URL 생성만)
    url = get_character_image_url("cain", "test_character_id")

    assert isinstance(url, str), "반환값은 문자열이어야 한다"
    assert "img-api.neople.co.kr" in url, "네오플 이미지 API 도메인 포함 필수"
    assert "cain" in url, "서버 ID가 URL에 포함되어야 한다"
    assert "test_character_id" in url, "캐릭터 ID가 URL에 포함되어야 한다"


async def test_get_character_image_url_with_real_character():
    """실제 캐릭터로 생성된 이미지 URL이 올바른 형식이어야 한다."""
    search = await search_characters("casillas", "김철완")
    if search is None or not search.get("rows"):
        pytest.skip("캐릭터 검색 실패")

    row = search["rows"][0]
    url = get_character_image_url(row["serverId"], row["characterId"])

    assert "img-api.neople.co.kr" in url
    assert row["serverId"] in url
    assert row["characterId"] in url


# ─── 아이템 상세 (장착 레벨) 테스트 ───


async def test_fetch_item_detail_returns_int():
    """무색 큐브 조각 아이템 ID로 조회하면 장착 레벨(int)을 반환해야 한다."""
    # 무색 큐브 조각 (언커먼, 고정 아이템)
    known_item_id = "785e56a0ed4e3efd573da1f56a45217d"

    result = await fetch_item_detail(known_item_id)

    assert isinstance(result, int), "반환값은 int여야 한다"


async def test_fetch_item_detail_unknown_item():
    """존재하지 않는 아이템 ID로 조회하면 0을 반환해야 한다."""
    fake_item_id = "0000000000000000000000000000000000"

    result = await fetch_item_detail(fake_item_id)

    assert isinstance(result, int), "반환값은 int여야 한다"
    assert result == 0, "존재하지 않는 아이템은 0을 반환해야 한다"


# ─── 타임라인 테스트 ───


async def test_fetch_timeline():
    """실제 캐릭터의 타임라인을 조회하면 timeline 키가 포함된 dict를 반환해야 한다."""
    search = await search_characters("casillas", "김철완")
    if search is None or not search.get("rows"):
        pytest.skip("캐릭터 검색 실패 - 타임라인 테스트 스킵")

    row = search["rows"][0]
    server_id = row["serverId"]
    character_id = row["characterId"]

    result = await fetch_timeline(server_id, character_id)

    # API 장애 시 None 반환 허용
    if result is None:
        pytest.skip("타임라인 API가 응답하지 않음")

    assert isinstance(result, dict), "반환값은 dict여야 한다"
    assert "timeline" in result, "timeline 키가 존재해야 한다"


async def test_fetch_timeline_has_rows():
    """타임라인 응답의 timeline 객체 내에 rows 키가 있어야 한다."""
    search = await search_characters("casillas", "김철완")
    if search is None or not search.get("rows"):
        pytest.skip("캐릭터 검색 실패")

    row = search["rows"][0]
    result = await fetch_timeline(row["serverId"], row["characterId"])

    if result is None:
        pytest.skip("타임라인 API가 응답하지 않음")

    timeline = result.get("timeline", {})
    assert "rows" in timeline, "timeline 내에 rows 키가 있어야 한다"
    assert isinstance(timeline["rows"], list), "rows는 list여야 한다"
