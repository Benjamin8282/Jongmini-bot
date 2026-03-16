"""
core/dundam_api.py 실제 API 통합 테스트.

던담(dundam.xyz) 외부 랭킹 API를 직접 호출하여 응답 형식과 동작을 검증한다.
유효한 캐릭터 ID를 확보하기 위해 DNF 네오플 API도 함께 사용하므로
NEOPLE_API_KEY 환경변수가 설정되어 있어야 실행된다.
던담 API는 외부 서비스라 응답이 불안정할 수 있으므로,
None 결과를 실패가 아닌 스킵으로 처리한다.
"""
import os

import aiohttp
import pytest

# 던담 API 테스트에도 NEOPLE_API_KEY 필요 (캐릭터 검색용)
pytestmark = [
    pytest.mark.skipif(
        not os.getenv("NEOPLE_API_KEY"),
        reason="NEOPLE_API_KEY not set (던담 테스트에 캐릭터 검색 필요)",
    ),
    pytest.mark.asyncio,
]

from core.dnf_api import search_characters  # noqa: E402
from core.dundam_api import (  # noqa: E402
    _cache,
    fetch_dundam_data_with_retry,
    fetch_dundam_buffer_with_retry,
    fetch_all_with_rate_limit,
)


# ─── Helper: 유효한 캐릭터 정보 획득 ───


async def _get_valid_character():
    """DNF API 검색으로 유효한 캐릭터 dict를 구성한다. 실패 시 None."""
    search = await search_characters("casillas", "김철완")
    if search is None or not search.get("rows"):
        return None

    row = search["rows"][0]
    return {
        "character_id": row["characterId"],
        "server_id": row["serverId"],
        "character_name": row["characterName"],
        "adventure_name": row.get("adventureName", ""),
    }


def _clear_dundam_cache():
    """던담 API 내부 캐시 초기화 (테스트 격리용)."""
    _cache.clear()


# ─── 딜러 던담 데이터 조회 테스트 ───


async def test_fetch_dundam_data_with_retry_returns_damage():
    """유효한 캐릭터의 던담 딜러 데이터를 조회하면 damage 키가 포함된 dict를 반환해야 한다."""
    _clear_dundam_cache()
    character = await _get_valid_character()
    if character is None:
        pytest.skip("유효한 캐릭터를 검색할 수 없음")

    async with aiohttp.ClientSession() as session:
        result = await fetch_dundam_data_with_retry(session, character)

    # 던담 API가 응답하지 않거나 해당 캐릭터에 데이터가 없을 수 있음
    if result is None:
        pytest.skip("던담 API가 데이터를 반환하지 않음 (타임아웃 또는 데이터 없음)")

    assert isinstance(result, dict), "반환값은 dict여야 한다"
    assert "damage" in result, "damage 키가 존재해야 한다"
    assert isinstance(result["damage"], int), "damage 값은 int여야 한다"
    assert result["damage"] > 0, "damage는 양수여야 한다"


async def test_fetch_dundam_data_result_has_character_info():
    """던담 응답에 character_name, server_id 등 캐릭터 기본 정보가 포함되어야 한다."""
    _clear_dundam_cache()
    character = await _get_valid_character()
    if character is None:
        pytest.skip("유효한 캐릭터를 검색할 수 없음")

    async with aiohttp.ClientSession() as session:
        result = await fetch_dundam_data_with_retry(session, character)

    if result is None:
        pytest.skip("던담 API가 데이터를 반환하지 않음")

    assert "character_name" in result, "character_name 키 필수"
    assert "character_id" in result, "character_id 키 필수"
    assert "server_id" in result, "server_id 키 필수"


# ─── 버퍼 던담 데이터 조회 테스트 ───


async def _get_buffer_character():
    """버퍼 캐릭터 정보 획득 (카시야스/잘빠라메딕)."""
    search = await search_characters("casillas", "잘빠라메딕")
    if search is None or not search.get("rows"):
        return None
    row = search["rows"][0]
    return {
        "character_id": row["characterId"],
        "server_id": row["serverId"],
        "character_name": row["characterName"],
        "adventure_name": row.get("adventureName", ""),
    }


async def test_fetch_dundam_buffer_with_retry():
    """버퍼 캐릭터 데이터 조회 시 buff_score 키가 포함된 dict 또는 None을 반환해야 한다."""
    _clear_dundam_cache()
    character = await _get_buffer_character()
    if character is None:
        pytest.skip("버퍼 캐릭터를 검색할 수 없음")

    async with aiohttp.ClientSession() as session:
        result = await fetch_dundam_buffer_with_retry(session, character)

    if result is None:
        pytest.skip("던담 API 미응답")

    assert isinstance(result, dict), "반환값은 dict여야 한다"
    assert "buff_score" in result, "buff_score 키가 존재해야 한다"
    assert isinstance(result["buff_score"], int), "buff_score 값은 int여야 한다"
    assert result["buff_score"] > 0, "buff_score는 양수여야 한다"


# ─── 전체 캐릭터 일괄 조회 테스트 ───


async def test_fetch_all_with_rate_limit_returns_list():
    """여러 캐릭터를 rate limit 적용하여 일괄 조회하면 list를 반환해야 한다."""
    _clear_dundam_cache()
    character = await _get_valid_character()
    if character is None:
        pytest.skip("유효한 캐릭터를 검색할 수 없음")

    # 동일 캐릭터 2개로 최소 테스트 (API 부하 최소화)
    characters = [character, character]

    async with aiohttp.ClientSession() as session:
        results = await fetch_all_with_rate_limit(
            session, characters, limit_per_second=2,
        )

    assert isinstance(results, list), "반환값은 list여야 한다"
    assert len(results) == len(characters), (
        f"입력 캐릭터 수({len(characters)})와 결과 수({len(results)})가 일치해야 한다"
    )


async def test_fetch_all_with_rate_limit_empty_input():
    """빈 캐릭터 리스트로 호출하면 빈 리스트를 반환해야 한다."""
    _clear_dundam_cache()

    async with aiohttp.ClientSession() as session:
        results = await fetch_all_with_rate_limit(session, [], limit_per_second=5)

    assert isinstance(results, list), "반환값은 list여야 한다"
    assert len(results) == 0, "빈 입력에 대해 빈 리스트 반환"


# ─── 캐시 동작 테스트 ───


async def test_dundam_cache_hit_on_second_call():
    """동일 캐릭터를 연속 조회하면 두 번째 호출은 캐시에서 즉시 반환해야 한다."""
    _clear_dundam_cache()
    character = await _get_valid_character()
    if character is None:
        pytest.skip("유효한 캐릭터를 검색할 수 없음")

    async with aiohttp.ClientSession() as session:
        # 첫 번째 호출: API 직접 호출
        first = await fetch_dundam_data_with_retry(session, character)

        if first is None:
            pytest.skip("던담 API가 데이터를 반환하지 않음")

        # 두 번째 호출: 캐시 히트 (같은 세션 내)
        second = await fetch_dundam_data_with_retry(session, character)

    assert second is not None, "캐시 히트 시 None이 아니어야 한다"
    assert first == second, "캐시된 결과와 원본 결과가 동일해야 한다"


# ─── 잘못된 캐릭터 ID 처리 테스트 ───


async def test_fetch_dundam_data_invalid_character():
    """존재하지 않는 캐릭터 ID로 조회하면 None을 반환해야 한다."""
    _clear_dundam_cache()
    invalid_character = {
        "character_id": "00000000000000000000000000000000",
        "server_id": "casillas",
        "character_name": "존재하지않는캐릭터",
        "adventure_name": "테스트모험단",
    }

    async with aiohttp.ClientSession() as session:
        result = await fetch_dundam_data_with_retry(
            session, invalid_character, retries=1,
        )

    # 잘못된 ID에 대해 None 반환 (에러 핸들링 확인)
    assert result is None, "존재하지 않는 캐릭터에 대해 None을 반환해야 한다"
