import aiosqlite
from pathlib import Path
from core.logger import logger
from core.models import SERVER_MAP

DB_PATH = Path("data/characters.db")


async def init_db():
    logger.info("DB 초기화 시작")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            # 캐릭터 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS characters (
                    character_id TEXT PRIMARY KEY,
                    character_name TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    level INTEGER,
                    job_name TEXT,
                    job_grow_name TEXT,
                    adventure_name TEXT NOT NULL
                )
            """)
            # 사용자-캐릭터 등록 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS registrations (
                    user_id INTEGER NOT NULL,
                    character_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, character_id),
                    FOREIGN KEY(character_id) REFERENCES characters(character_id)
                )
            """)
            # 아이템 캐시 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS item_cache (
                    item_id TEXT PRIMARY KEY,
                    item_available_level INTEGER NOT NULL
                )
            """)
            # 출력 채널 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS output_channels (
                    guild_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 캐릭터별 마지막 타임라인 체크 시간 기록 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS character_last_checked (
                    character_id TEXT PRIMARY KEY,
                    last_checked TEXT NOT NULL
                )
            """)
            # 일간 집계 마지막 실행 시간 기록 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_aggregation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    last_aggregation_time TEXT NOT NULL
                )
            """)
            # 모험단별 검색 제외 설정 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS adventure_exclusions (
                    adventure_name TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    is_excluded INTEGER DEFAULT 0,
                    PRIMARY KEY (adventure_name, server_id)
                )
            """)
            # 레이드 퍼스트 클리어 기록 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS raid_first_clears (
                    raid_key TEXT PRIMARY KEY,
                    first_party_name TEXT,
                    first_clear_date TEXT,
                    first_members TEXT,
                    second_party_name TEXT,
                    second_clear_date TEXT,
                    second_members TEXT,
                    third_party_name TEXT,
                    third_clear_date TEXT,
                    third_members TEXT,
                    last_check_date TEXT
                )
            """)
            # 임시 레이드 클리어 정보 테이블 (1분 대기용)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS temp_raid_clears (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_id TEXT,
                    character_name TEXT,
                    adventure_name TEXT,
                    raid_party_name TEXT,
                    clear_date TEXT,
                    raid_name TEXT,
                    mode_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.commit()
        logger.info("DB 초기화 완료")
    except Exception as e:
        logger.error(f"DB 초기화 실패: {e}")


# ----- 캐릭터 관리 -----

async def save_character(character: dict):
    logger.info(f"캐릭터 저장 시도: {character['characterName']} ({character['characterId']})")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO characters
                (character_id, character_name, server_id, level, job_name, job_grow_name, adventure_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                character["characterId"],
                character["characterName"],
                character["serverId"],
                character["level"],
                character["jobName"],
                character["jobGrowName"],
                character["adventureName"],
            ))
            await conn.commit()
        logger.info(f"캐릭터 저장 성공: {character['characterName']} ({character['characterId']})")
    except Exception as e:
        logger.error(f"캐릭터 저장 실패: {e}")


async def register_character(user_id: int, character_id: str):
    logger.info(f"사용자 {user_id} 캐릭터 등록 시도: {character_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                INSERT OR IGNORE INTO registrations (user_id, character_id)
                VALUES (?, ?)
            """, (user_id, character_id))
            await conn.commit()
        logger.info(f"사용자 {user_id} 캐릭터 등록 성공: {character_id}")
    except Exception as e:
        logger.error(f"사용자 {user_id} 캐릭터 등록 실패: {e}")


async def get_characters_by_adventure_name(adventure_name: str) -> list[dict]:
    logger.info(f"모험단 이름으로 캐릭터 조회 시도: {adventure_name}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM characters
                WHERE adventure_name = ?
            """, (adventure_name,))
            rows = await cursor.fetchall()
        logger.info(f"모험단 '{adventure_name}' 조회 성공: {len(rows)}개 캐릭터")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"모험단 '{adventure_name}' 조회 실패: {e}")
        return []


async def get_characters_by_user(user_id: int) -> list[dict]:
    logger.info(f"사용자 {user_id} 등록 캐릭터 조회 시도")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT c.*
                FROM characters c
                JOIN registrations r ON c.character_id = r.character_id
                WHERE r.user_id = ?
            """, (user_id,))
            rows = await cursor.fetchall()
        logger.info(f"사용자 {user_id} 등록 캐릭터 조회 성공: {len(rows)}개")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"사용자 {user_id} 등록 캐릭터 조회 실패: {e}")
        return []


async def get_all_characters_grouped_by_adventure() -> dict[str, list[dict]]:
    logger.info("전체 캐릭터 모험단별 조회 시도")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM characters
                ORDER BY adventure_name, server_id, character_name
            """)
            rows = await cursor.fetchall()
            grouped = {}
            for row in rows:
                adv_name = f"{row['adventure_name']} ({SERVER_MAP.get(row['server_id'], row['server_id'])})"
                grouped.setdefault(adv_name, []).append(dict(row))
        logger.info(f"전체 캐릭터 모험단별 조회 성공: {len(rows)}개 캐릭터")
        return grouped
    except Exception as e:
        logger.error(f"전체 캐릭터 모험단별 조회 실패: {e}")
        return {}


# ----- 아이템 캐시 -----

async def get_item_available_level(item_id: str) -> int | None:
    logger.info(f"아이템 캐시 조회 시도: {item_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT item_available_level FROM item_cache WHERE item_id = ?", (item_id,))
            row = await cursor.fetchone()
            if row:
                logger.info(f"아이템 캐시 조회 성공: {item_id} 레벨 {row['item_available_level']}")
                return row["item_available_level"]
            else:
                logger.info(f"아이템 캐시 없음: {item_id}")
                return None
    except Exception as e:
        logger.error(f"아이템 캐시 조회 실패: {e}")
        return None


async def save_item_available_level(item_id: str, level: int):
    logger.info(f"아이템 캐시 저장 시도: {item_id} 레벨 {level}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO item_cache (item_id, item_available_level) VALUES (?, ?)",
                (item_id, level))
            await conn.commit()
        logger.info(f"아이템 캐시 저장 성공: {item_id} 레벨 {level}")
    except Exception as e:
        logger.error(f"아이템 캐시 저장 실패: {e}")


# ----- 출력 채널 -----

async def save_output_channel(guild_id: str, channel_id: str):
    logger.info(f"출력 채널 저장 시도: guild={guild_id}, channel={channel_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO output_channels (guild_id, channel_id) VALUES (?, ?)",
                (guild_id, channel_id)
            )
            await conn.commit()
        logger.info("출력 채널 저장 성공")
    except Exception as e:
        logger.error(f"출력 채널 저장 실패: {e}")


async def get_output_channel(guild_id: str) -> str | None:
    logger.info(f"출력 채널 조회 시도: guild={guild_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT channel_id FROM output_channels WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if row:
                return row["channel_id"]
            else:
                return None
    except Exception as e:
        logger.error(f"출력 채널 조회 실패: {e}")
        return None


# ----- 캐릭터별 타임라인 체크 기록 -----

async def get_last_checked(character_id: str) -> str | None:
    logger.info(f"캐릭터 마지막 조회시각 조회 시도: {character_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT last_checked FROM character_last_checked WHERE character_id = ?",
                (character_id,))
            row = await cursor.fetchone()
            if row:
                return row["last_checked"]
            else:
                return None
    except Exception as e:
        logger.error(f"캐릭터 마지막 조회시각 조회 실패: {e}")
        return None


async def update_last_checked(character_id: str, last_checked: str):
    logger.info(f"캐릭터 마지막 조회시각 업데이트: {character_id} -> {last_checked}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO character_last_checked (character_id, last_checked) VALUES (?, ?)",
                (character_id, last_checked)
            )
            await conn.commit()
        logger.info("캐릭터 마지막 조회시각 저장 성공")
    except Exception as e:
        logger.error(f"캐릭터 마지막 조회시각 저장 실패: {e}")


async def get_last_aggregation_time() -> str | None:
    """
    가장 최근 일간 집계 시간 조회 (문자열, 'YYYYMMDDTHHMM' 포맷)
    """
    logger.info("일간 집계 마지막 실행 시간 조회 시도")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT last_aggregation_time FROM daily_aggregation_log ORDER BY id DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            if row:
                logger.info(f"마지막 집계 시간 조회 성공: {row['last_aggregation_time']}")
                return row["last_aggregation_time"]
            else:
                logger.info("마지막 집계 시간 기록 없음")
                return None
    except Exception as e:
        logger.error(f"일간 집계 마지막 실행 시간 조회 실패: {e}")
        return None


async def update_last_aggregation_time(timestamp_str: str):
    """
    집계 작업 완료 후 실행 시간 저장
    """
    logger.info(f"일간 집계 실행 시간 저장 시도: {timestamp_str}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT INTO daily_aggregation_log (last_aggregation_time) VALUES (?)",
                (timestamp_str,)
            )
            await conn.commit()
        logger.info("일간 집계 실행 시간 저장 성공")
    except Exception as e:
        logger.error(f"일간 집계 실행 시간 저장 실패: {e}")


async def get_all_characters() -> list[dict]:
    logger.info("DB에서 전체 캐릭터 조회 시도")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM characters
                ORDER BY adventure_name, server_id, character_name
            """)
            rows = await cursor.fetchall()
        logger.info(f"전체 캐릭터 조회 성공: {len(rows)}개")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"전체 캐릭터 조회 실패: {e}")
        return []


async def update_character_name(character_id: str, new_name: str):
    """
    캐릭터 이름이 변경된 경우 DB 업데이트
    """
    logger.info(f"캐릭터 이름 업데이트 시도: {character_id} -> {new_name}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "UPDATE characters SET character_name = ? WHERE character_id = ?",
                (new_name, character_id)
            )
            await conn.commit()
        logger.info(f"캐릭터 이름 업데이트 성공: {new_name}")
    except Exception as e:
        logger.error(f"캐릭터 이름 업데이트 실패: {e}")


# ----- 모험단 검색 제외 관리 -----

async def get_all_adventures() -> list[dict]:
    """
    등록된 모든 모험단 목록 반환 (중복 제거)
    반환 형식: [{"adventure_name": str, "server_id": str, "is_excluded": int}, ...]
    """
    logger.info("전체 모험단 목록 조회 시도")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            # 고유한 모험단 목록 조회
            cursor = await conn.execute("""
                SELECT DISTINCT c.adventure_name, c.server_id,
                       COALESCE(e.is_excluded, 0) as is_excluded
                FROM characters c
                LEFT JOIN adventure_exclusions e
                    ON c.adventure_name = e.adventure_name
                    AND c.server_id = e.server_id
                ORDER BY c.adventure_name, c.server_id
            """)
            rows = await cursor.fetchall()
        logger.info(f"전체 모험단 조회 성공: {len(rows)}개")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"전체 모험단 조회 실패: {e}")
        return []


async def get_adventure_exclusion_status(adventure_name: str, server_id: str) -> bool:
    """
    특정 모험단의 검색 제외 상태 조회
    반환: True면 제외됨, False면 포함됨
    """
    logger.info(f"모험단 제외 상태 조회: {adventure_name} ({server_id})")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT is_excluded FROM adventure_exclusions
                WHERE adventure_name = ? AND server_id = ?
            """, (adventure_name, server_id))
            row = await cursor.fetchone()
            if row:
                return bool(row["is_excluded"])
            else:
                return False  # 기본값: 포함
    except Exception as e:
        logger.error(f"모험단 제외 상태 조회 실패: {e}")
        return False


async def set_adventure_exclusion(adventure_name: str, server_id: str, is_excluded: bool):
    """
    모험단의 검색 제외 상태 설정
    """
    logger.info(f"모험단 제외 상태 설정: {adventure_name} ({server_id}) -> {is_excluded}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO adventure_exclusions (adventure_name, server_id, is_excluded)
                VALUES (?, ?, ?)
            """, (adventure_name, server_id, 1 if is_excluded else 0))
            await conn.commit()
        logger.info("모험단 제외 상태 설정 성공")
    except Exception as e:
        logger.error(f"모험단 제외 상태 설정 실패: {e}")


async def get_active_characters() -> list[dict]:
    """
    검색에서 제외되지 않은 모험단의 캐릭터만 반환
    """
    logger.info("활성 캐릭터 조회 시도 (제외된 모험단 필터링)")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT c.*
                FROM characters c
                LEFT JOIN adventure_exclusions e
                    ON c.adventure_name = e.adventure_name
                    AND c.server_id = e.server_id
                WHERE COALESCE(e.is_excluded, 0) = 0
                ORDER BY c.adventure_name, c.server_id, c.character_name
            """)
            rows = await cursor.fetchall()
        logger.info(f"활성 캐릭터 조회 성공: {len(rows)}개")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"활성 캐릭터 조회 실패: {e}")
        return []


# ----- 레이드 퍼스트 클리어 관리 -----

async def save_temp_raid_clear(clear_info: dict):
    """임시 레이드 클리어 정보 저장"""
    logger.info(f"임시 레이드 클리어 저장: {clear_info['character_name']} - {clear_info['raid_party_name']}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                INSERT INTO temp_raid_clears
                (character_id, character_name, adventure_name, raid_party_name,
                 clear_date, raid_name, mode_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                clear_info['character_id'],
                clear_info['character_name'],
                clear_info['adventure_name'],
                clear_info['raid_party_name'],
                clear_info['clear_date'],
                clear_info['raid_name'],
                clear_info['mode_name']
            ))
            await conn.commit()
        logger.info("임시 레이드 클리어 저장 성공")
    except Exception as e:
        logger.error(f"임시 레이드 클리어 저장 실패: {e}")


async def get_recent_temp_clears(minutes: int = 2) -> list[dict]:
    """최근 N분 내 임시 클리어 조회"""
    logger.info(f"최근 {minutes}분 내 임시 클리어 조회")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM temp_raid_clears
                WHERE datetime(created_at) >= datetime('now', '-' || ? || ' minutes')
                ORDER BY clear_date
            """, (minutes,))
            rows = await cursor.fetchall()
        logger.info(f"임시 클리어 조회 성공: {len(rows)}개")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"임시 클리어 조회 실패: {e}")
        return []


async def clear_temp_raid_clears():
    """임시 클리어 정보 삭제"""
    logger.info("임시 클리어 정보 삭제 시도")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("DELETE FROM temp_raid_clears")
            await conn.commit()
        logger.info("임시 클리어 정보 삭제 성공")
    except Exception as e:
        logger.error(f"임시 클리어 정보 삭제 실패: {e}")


async def get_raid_rank(raid_key: str) -> dict | None:
    """레이드 현재 순위 정보 조회"""
    logger.info(f"레이드 순위 조회: {raid_key}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM raid_first_clears WHERE raid_key = ?
            """, (raid_key,))
            row = await cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"레이드 순위 조회 실패: {e}")
        return None


async def save_raid_first_clear(raid_key: str, rank: int, party_info: dict):
    """레이드 퍼스트 클리어 기록"""
    import json
    logger.info(f"레이드 {rank}위 기록: {raid_key} - {party_info['party_name']}")

    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            # 기존 데이터 조회
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM raid_first_clears WHERE raid_key = ?
            """, (raid_key,))
            existing = await cursor.fetchone()

            members_json = json.dumps(party_info['members'], ensure_ascii=False)

            if existing:
                # 업데이트
                if rank == 1:
                    await conn.execute("""
                        UPDATE raid_first_clears
                        SET first_party_name = ?, first_clear_date = ?, first_members = ?
                        WHERE raid_key = ?
                    """, (party_info['party_name'], party_info['clear_time'], members_json, raid_key))
                elif rank == 2:
                    await conn.execute("""
                        UPDATE raid_first_clears
                        SET second_party_name = ?, second_clear_date = ?, second_members = ?
                        WHERE raid_key = ?
                    """, (party_info['party_name'], party_info['clear_time'], members_json, raid_key))
                elif rank == 3:
                    await conn.execute("""
                        UPDATE raid_first_clears
                        SET third_party_name = ?, third_clear_date = ?, third_members = ?
                        WHERE raid_key = ?
                    """, (party_info['party_name'], party_info['clear_time'], members_json, raid_key))
            else:
                # 새 레코드 생성
                if rank == 1:
                    await conn.execute("""
                        INSERT INTO raid_first_clears
                        (raid_key, first_party_name, first_clear_date, first_members)
                        VALUES (?, ?, ?, ?)
                    """, (raid_key, party_info['party_name'], party_info['clear_time'], members_json))
                elif rank == 2:
                    await conn.execute("""
                        INSERT INTO raid_first_clears
                        (raid_key, second_party_name, second_clear_date, second_members)
                        VALUES (?, ?, ?, ?)
                    """, (raid_key, party_info['party_name'], party_info['clear_time'], members_json))
                elif rank == 3:
                    await conn.execute("""
                        INSERT INTO raid_first_clears
                        (raid_key, third_party_name, third_clear_date, third_members)
                        VALUES (?, ?, ?, ?)
                    """, (raid_key, party_info['party_name'], party_info['clear_time'], members_json))

            await conn.commit()
        logger.info(f"레이드 {rank}위 기록 성공")
    except Exception as e:
        logger.error(f"레이드 클리어 기록 실패: {e}")
