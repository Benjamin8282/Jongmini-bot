"""core.db 모듈 테스트."""
import pytest
import pytest_asyncio

import core.db as db


# ─── init_db ───


@pytest.mark.asyncio
async def test_init_db_테이블_생성(test_db):
    """init_db 호출 후 주요 테이블이 생성되어 있다."""
    import aiosqlite
    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
    table_names = {row[0] for row in rows}
    expected_tables = {
        "characters",
        "registrations",
        "item_cache",
        "output_channels",
        "character_last_checked",
        "daily_aggregation_log",
        "adventure_exclusions",
        "auction_watch_items",
        "auction_price_history",
        "user_alert_settings",
        "activity_basket",
        "dundam_ranking_cache",
        "job_skill_options",
        "dundam_daily_usage",
    }
    assert expected_tables.issubset(table_names)


@pytest.mark.asyncio
async def test_init_db_재실행_안전(test_db):
    """init_db를 두 번 호출해도 에러가 발생하지 않는다 (CREATE IF NOT EXISTS)."""
    await db.init_db()  # 두 번째 호출
    # 에러 없이 통과하면 성공


# ─── 캐릭터 CRUD ───


@pytest.mark.asyncio
async def test_save_and_get_character(test_db):
    """캐릭터를 저장하고 전체 조회로 확인한다."""
    character = {
        "characterId": "test-char-001",
        "characterName": "테스트캐릭",
        "serverId": "cain",
        "level": 110,
        "jobName": "귀검사(남)",
        "jobGrowName": "웨펀마스터",
        "adventureName": "테스트모험단",
    }
    await db.save_character(character)

    all_chars = await db.get_all_characters()
    assert len(all_chars) >= 1
    found = [c for c in all_chars if c["character_id"] == "test-char-001"]
    assert len(found) == 1
    assert found[0]["character_name"] == "테스트캐릭"
    assert found[0]["server_id"] == "cain"
    assert found[0]["level"] == 110


@pytest.mark.asyncio
async def test_register_character(test_db):
    """사용자-캐릭터 등록 후 조회한다."""
    character = {
        "characterId": "test-char-002",
        "characterName": "등록캐릭",
        "serverId": "bakal",
        "level": 110,
        "jobName": "마법사(여)",
        "jobGrowName": "엘레멘탈마스터",
        "adventureName": "모험단A",
    }
    await db.save_character(character)
    await db.register_character(user_id=12345, character_id="test-char-002")

    chars = await db.get_characters_by_user(12345)
    assert len(chars) >= 1
    found = [c for c in chars if c["character_id"] == "test-char-002"]
    assert len(found) == 1
    assert found[0]["character_name"] == "등록캐릭"


@pytest.mark.asyncio
async def test_get_all_characters_비어있을때(test_db):
    """캐릭터가 없으면 빈 리스트를 반환한다."""
    chars = await db.get_all_characters()
    assert chars == []


@pytest.mark.asyncio
async def test_get_active_characters_제외_필터링(test_db):
    """제외된 모험단의 캐릭터는 활성 목록에서 빠진다."""
    char_active = {
        "characterId": "active-001",
        "characterName": "활성캐릭",
        "serverId": "cain",
        "level": 110,
        "jobName": "격투가(남)",
        "jobGrowName": "스트라이커",
        "adventureName": "활성모험단",
    }
    char_excluded = {
        "characterId": "excluded-001",
        "characterName": "제외캐릭",
        "serverId": "cain",
        "level": 110,
        "jobName": "거너(남)",
        "jobGrowName": "레인저",
        "adventureName": "제외모험단",
    }
    await db.save_character(char_active)
    await db.save_character(char_excluded)

    # 제외 모험단 설정
    await db.set_adventure_exclusion("제외모험단", "cain", True)

    active = await db.get_active_characters()
    active_ids = [c["character_id"] for c in active]
    assert "active-001" in active_ids
    assert "excluded-001" not in active_ids


@pytest.mark.asyncio
async def test_get_active_characters_제외_없으면_전체(test_db):
    """제외 설정이 없으면 전체 캐릭터가 활성 목록에 포함된다."""
    char = {
        "characterId": "all-active-001",
        "characterName": "전체캐릭",
        "serverId": "bakal",
        "level": 110,
        "jobName": "프리스트(남)",
        "jobGrowName": "크루세이더",
        "adventureName": "전체모험단",
    }
    await db.save_character(char)

    active = await db.get_active_characters()
    active_ids = [c["character_id"] for c in active]
    assert "all-active-001" in active_ids


# ─── 경매장 시세 감시 아이템 ───


@pytest.mark.asyncio
async def test_add_watch_item(test_db):
    """감시 아이템을 등록하면 True, 중복이면 False 를 반환한다."""
    result = await db.add_watch_item("item-001", "불꽃의 검", 99999)
    assert result is True

    # 중복 등록
    result_dup = await db.add_watch_item("item-001", "불꽃의 검", 99999)
    assert result_dup is False


@pytest.mark.asyncio
async def test_get_all_watch_items(test_db):
    """등록한 감시 아이템 목록을 조회한다."""
    await db.add_watch_item("item-010", "얼음의 창", 11111)
    await db.add_watch_item("item-011", "바람의 활", 11111)

    items = await db.get_all_watch_items()
    assert len(items) >= 2
    names = [it["item_name"] for it in items]
    assert "얼음의 창" in names
    assert "바람의 활" in names


@pytest.mark.asyncio
async def test_get_watch_item_by_name(test_db):
    """아이템 이름으로 감시 아이템을 조회한다."""
    await db.add_watch_item("item-020", "번개의 망치", 22222)

    found = await db.get_watch_item_by_name("번개의 망치")
    assert found is not None
    assert found["item_id"] == "item-020"
    assert found["item_name"] == "번개의 망치"
    assert found["registered_by"] == 22222


@pytest.mark.asyncio
async def test_get_watch_item_by_name_없는_아이템(test_db):
    """존재하지 않는 이름으로 조회하면 None 을 반환한다."""
    result = await db.get_watch_item_by_name("존재하지않는아이템")
    assert result is None


@pytest.mark.asyncio
async def test_remove_watch_item(test_db):
    """감시 아이템을 해제하면 목록에서 사라진다."""
    await db.add_watch_item("item-030", "삭제할검", 33333)
    items_before = await db.get_all_watch_items()
    ids_before = [it["item_id"] for it in items_before]
    assert "item-030" in ids_before

    await db.remove_watch_item("item-030")

    items_after = await db.get_all_watch_items()
    ids_after = [it["item_id"] for it in items_after]
    assert "item-030" not in ids_after


# ─── 가격 이력 ───


@pytest.mark.asyncio
async def test_save_and_get_price_history(test_db):
    """가격 이력을 저장하고 기간 조회한다."""
    records = [
        {
            "item_id": "price-item-001",
            "sold_date": "2025-06-01 10:00:00",
            "unit_price": 15000,
            "price": 15000,
            "count": 1,
        },
        {
            "item_id": "price-item-001",
            "sold_date": "2025-06-01 11:00:00",
            "unit_price": 16000,
            "price": 32000,
            "count": 2,
        },
        {
            "item_id": "price-item-001",
            "sold_date": "2025-06-02 09:00:00",
            "unit_price": 14000,
            "price": 14000,
            "count": 1,
        },
    ]
    await db.save_auction_prices(records)

    # 전체 기간 조회
    history = await db.get_price_history(
        "price-item-001", "2025-06-01 00:00:00", "2025-06-02 23:59:59"
    )
    assert len(history) == 3

    # 부분 기간 조회
    history_partial = await db.get_price_history(
        "price-item-001", "2025-06-01 00:00:00", "2025-06-01 23:59:59"
    )
    assert len(history_partial) == 2


@pytest.mark.asyncio
async def test_save_price_history_중복_스킵(test_db):
    """동일한 거래 이력을 중복 저장해도 에러 없이 무시된다."""
    record = {
        "item_id": "dup-item-001",
        "sold_date": "2025-07-01 12:00:00",
        "unit_price": 20000,
        "price": 20000,
        "count": 1,
    }
    await db.save_auction_prices([record])
    await db.save_auction_prices([record])  # 중복

    history = await db.get_price_history(
        "dup-item-001", "2025-07-01 00:00:00", "2025-07-01 23:59:59"
    )
    assert len(history) == 1


@pytest.mark.asyncio
async def test_get_price_history_빈_결과(test_db):
    """존재하지 않는 아이템 조회 시 빈 리스트."""
    history = await db.get_price_history(
        "nonexistent-item", "2025-01-01 00:00:00", "2025-12-31 23:59:59"
    )
    assert history == []


# ─── 출력 채널 ───


@pytest.mark.asyncio
async def test_save_typed_output_channel_item(test_db):
    """아이템 타입 출력 채널을 저장하고 조회한다."""
    await db.save_typed_output_channel("guild-001", "item", "ch-item-001")

    channel = await db.get_output_channel("guild-001", "item")
    assert channel == "ch-item-001"


@pytest.mark.asyncio
async def test_save_typed_output_channel_economy(test_db):
    """경제 타입 출력 채널을 저장하고 조회한다."""
    await db.save_typed_output_channel("guild-002", "economy", "ch-eco-001")

    channel = await db.get_output_channel("guild-002", "economy")
    assert channel == "ch-eco-001"


@pytest.mark.asyncio
async def test_get_output_channel_폴백(test_db):
    """타입별 채널이 없으면 기본 channel_id로 폴백한다."""
    await db.save_output_channel("guild-003", "ch-default-003")

    # item 타입 미설정 → channel_id 폴백
    channel = await db.get_output_channel("guild-003", "item")
    assert channel == "ch-default-003"

    # economy 타입 미설정 → channel_id 폴백
    channel_eco = await db.get_output_channel("guild-003", "economy")
    assert channel_eco == "ch-default-003"


@pytest.mark.asyncio
async def test_get_output_channel_미등록_길드(test_db):
    """등록하지 않은 길드는 None 을 반환한다."""
    result = await db.get_output_channel("nonexistent-guild")
    assert result is None


@pytest.mark.asyncio
async def test_get_all_output_channels(test_db):
    """길드의 모든 출력 채널 설정을 조회한다."""
    await db.save_output_channel("guild-004", "ch-default-004")
    await db.save_typed_output_channel("guild-004", "item", "ch-item-004")
    await db.save_typed_output_channel("guild-004", "economy", "ch-eco-004")

    channels = await db.get_all_output_channels("guild-004")
    assert channels is not None
    assert channels["channel_id"] == "ch-default-004"
    assert channels["item_channel_id"] == "ch-item-004"
    assert channels["economy_channel_id"] == "ch-eco-004"


@pytest.mark.asyncio
async def test_get_all_output_channels_미등록(test_db):
    """미등록 길드는 None 을 반환한다."""
    result = await db.get_all_output_channels("nonexistent-guild-999")
    assert result is None


@pytest.mark.asyncio
async def test_output_channel_타입없이_조회(test_db):
    """channel_type=None 으로 조회하면 기본 channel_id 를 반환한다."""
    await db.save_output_channel("guild-005", "ch-default-005")

    channel = await db.get_output_channel("guild-005", None)
    assert channel == "ch-default-005"
