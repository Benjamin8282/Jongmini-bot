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
                    item_channel_id TEXT,
                    economy_channel_id TEXT,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 기존 테이블에 새 컬럼 추가 (마이그레이션)
            try:
                await conn.execute("ALTER TABLE output_channels ADD COLUMN item_channel_id TEXT")
            except Exception:
                pass  # 이미 존재하면 무시
            try:
                await conn.execute("ALTER TABLE output_channels ADD COLUMN economy_channel_id TEXT")
            except Exception:
                pass  # 이미 존재하면 무시
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
            # 경매장 시세 감시 아이템 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS auction_watch_items (
                    item_id TEXT PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    registered_by INTEGER NOT NULL,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 경매장 거래 가격 이력 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS auction_price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    sold_date TEXT NOT NULL,
                    unit_price INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(item_id, sold_date, unit_price, count)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_aph_item_sold
                ON auction_price_history(item_id, sold_date)
            """)
            # 사용자별 알림 설정 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_alert_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    threshold_value REAL NOT NULL,
                    one_time INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, item_id, alert_type)
                )
            """)
            # 활동지수 바스켓 아이템 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_basket (
                    item_id TEXT PRIMARY KEY,
                    item_name TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 던담순위 캐시 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dundam_ranking_cache (
                    character_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    character_name TEXT,
                    adventure_name TEXT,
                    score INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (character_id, server_id, mode)
                )
            """)
            # 직업별 스킬개화 옵션 캐시
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS job_skill_options (
                    job_key TEXT PRIMARY KEY,
                    skill_vp_options TEXT NOT NULL,
                    skill_force_options TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            # 던담 API 일일 사용량 추적
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dundam_daily_usage (
                    date TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0
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


def _resolve_channel_from_row(row, channel_type: str | None) -> str:
    """row에서 channel_type에 맞는 채널 ID 반환 (폴백: channel_id)."""
    _type_column_map = {
        'item': 'item_channel_id',
        'economy': 'economy_channel_id',
    }
    col = _type_column_map.get(channel_type)
    if col and row[col]:
        return row[col]
    return row['channel_id']


async def get_output_channel(guild_id: str, channel_type: str | None = None) -> str | None:
    """
    출력 채널 조회.
    channel_type: 'item' | 'economy' | None
    - 지정된 타입의 채널이 설정되어 있으면 해당 채널 반환
    - 없으면 기본 channel_id로 폴백 (하위 호환)
    """
    logger.info(f"출력 채널 조회 시도: guild={guild_id}, type={channel_type}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT channel_id, item_channel_id, economy_channel_id FROM output_channels WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return _resolve_channel_from_row(row, channel_type)
    except Exception as e:
        logger.error(f"출력 채널 조회 실패: {e}")
        return None


async def save_typed_output_channel(guild_id: str, channel_type: str, channel_id: str):
    """타입별 출력 채널 저장 (item / economy)"""
    column = 'item_channel_id' if channel_type == 'item' else 'economy_channel_id'
    logger.info(f"타입별 출력 채널 저장 시도: guild={guild_id}, type={channel_type}, channel={channel_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            # 행이 없으면 기본값으로 생성
            await conn.execute(
                "INSERT OR IGNORE INTO output_channels (guild_id, channel_id) VALUES (?, ?)",
                (guild_id, channel_id)
            )
            await conn.execute(
                f"UPDATE output_channels SET {column} = ? WHERE guild_id = ?",
                (channel_id, guild_id)
            )
            await conn.commit()
        logger.info(f"타입별 출력 채널 저장 성공: {channel_type} -> {channel_id}")
    except Exception as e:
        logger.error(f"타입별 출력 채널 저장 실패: {e}")


async def get_all_output_channels(guild_id: str) -> dict | None:
    """길드의 모든 출력 채널 설정 조회"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT channel_id, item_channel_id, economy_channel_id FROM output_channels WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"전체 출력 채널 조회 실패: {e}")
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


# ----- 경매장 시세 감시 -----

async def add_watch_item(item_id: str, item_name: str, user_id: int) -> bool:
    """감시 아이템 등록. 신규 등록이면 True, 이미 존재하면 False 반환"""
    logger.info(f"시세 감시 아이템 등록: {item_name} ({item_id})")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("""
                INSERT OR IGNORE INTO auction_watch_items
                (item_id, item_name, registered_by) VALUES (?, ?, ?)
            """, (item_id, item_name, user_id))
            await conn.commit()
            if cursor.rowcount == 0:
                logger.info(f"이미 등록된 감시 아이템: {item_name}")
                return False
        logger.info(f"시세 감시 아이템 등록 성공: {item_name}")
        return True
    except Exception as e:
        logger.error(f"시세 감시 아이템 등록 실패: {e}")
        return False


async def remove_watch_item(item_id: str):
    """감시 아이템 해제 (가격 이력은 보존)"""
    logger.info(f"시세 감시 아이템 해제: {item_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "DELETE FROM auction_watch_items WHERE item_id = ?",
                (item_id,)
            )
            await conn.commit()
        logger.info("시세 감시 아이템 해제 성공")
    except Exception as e:
        logger.error(f"시세 감시 아이템 해제 실패: {e}")


async def get_all_watch_items() -> list[dict]:
    """전체 감시 아이템 목록 반환"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM auction_watch_items ORDER BY registered_at"
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"감시 아이템 목록 조회 실패: {e}")
        return []


async def save_auction_prices(records: list[dict]):
    """거래 이력 벌크 저장 (중복 자동 스킵)"""
    if not records:
        return
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.executemany("""
                INSERT OR IGNORE INTO auction_price_history
                (item_id, sold_date, unit_price, price, count)
                VALUES (:item_id, :sold_date, :unit_price, :price, :count)
            """, records)
            await conn.commit()
        logger.info(f"경매장 거래 이력 저장: {len(records)}건")
    except Exception as e:
        logger.error(f"경매장 거래 이력 저장 실패: {e}")


async def get_price_history(item_id: str, start_date: str, end_date: str) -> list[dict]:
    """기간별 가격 이력 조회"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT sold_date, unit_price, price, count
                FROM auction_price_history
                WHERE item_id = ?
                  AND sold_date >= ? AND sold_date <= ?
                ORDER BY sold_date
            """, (item_id, start_date, end_date))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"가격 이력 조회 실패: {e}")
        return []


async def get_watch_item_by_name(item_name: str) -> dict | None:
    """아이템 이름으로 감시 아이템 조회"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM auction_watch_items WHERE item_name = ?",
                (item_name,)
            )
            row = await cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"감시 아이템 이름 조회 실패: {e}")
        return None


async def cleanup_old_price_history(days: int = 90):
    """오래된 거래 이력 정리"""
    try:
        modifier = f"-{int(days)} days"
        async with aiosqlite.connect(DB_PATH) as conn:
            result = await conn.execute("""
                DELETE FROM auction_price_history
                WHERE datetime(sold_date) < datetime('now', ?)
            """, (modifier,))
            await conn.commit()
        logger.info(f"오래된 거래 이력 정리 완료: {result.rowcount}건 삭제")
    except Exception as e:
        logger.error(f"거래 이력 정리 실패: {e}")


# ----- 활동지수 바스켓 -----

async def add_basket_item(item_id: str, item_name: str, user_id: int) -> bool:
    """바스켓 아이템 등록. 신규면 True, 이미 존재하면 False"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("""
                INSERT OR IGNORE INTO activity_basket
                (item_id, item_name, added_by) VALUES (?, ?, ?)
            """, (item_id, item_name, user_id))
            await conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"바스켓 아이템 등록 실패: {e}")
        return False


async def remove_basket_item(item_id: str):
    """바스켓 아이템 해제"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "DELETE FROM activity_basket WHERE item_id = ?", (item_id,)
            )
            await conn.commit()
    except Exception as e:
        logger.error(f"바스켓 아이템 해제 실패: {e}")


async def get_basket_items() -> list[dict]:
    """바스켓 아이템 목록 반환"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM activity_basket ORDER BY added_at"
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"바스켓 아이템 목록 조회 실패: {e}")
        return []


async def get_daily_volumes(item_id: str, days: int) -> list[dict]:
    """아이템의 일별 거래량 집계"""
    try:
        modifier = f"-{int(days)} days"
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT DATE(sold_date) as date, SUM(count) as volume
                FROM auction_price_history
                WHERE item_id = ?
                  AND datetime(sold_date) >= datetime('now', ?)
                GROUP BY DATE(sold_date)
                ORDER BY date
            """, (item_id, modifier))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"일별 거래량 조회 실패: {e}")
        return []


async def get_daily_avg_prices(item_id: str, days: int) -> list[dict]:
    """아이템의 일별 거래량 가중 평균가 집계"""
    try:
        modifier = f"-{int(days)} days"
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT DATE(sold_date) as date,
                       SUM(unit_price * count) * 1.0 / SUM(count) as avg_price,
                       SUM(count) as volume
                FROM auction_price_history
                WHERE item_id = ?
                  AND datetime(sold_date) >= datetime('now', ?)
                GROUP BY DATE(sold_date)
                ORDER BY date
            """, (item_id, modifier))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"일별 평균가 조회 실패: {e}")
        return []


# ----- 사용자별 알림 설정 -----

async def upsert_user_alert(
    user_id: int, item_id: str, alert_type: str,
    threshold_value: float, one_time: bool = False
):
    """사용자 알림 설정 저장 (있으면 업데이트)"""
    try:
        ot = 1 if one_time else 0
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                INSERT INTO user_alert_settings
                (user_id, item_id, alert_type, threshold_value, one_time, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(user_id, item_id, alert_type)
                DO UPDATE SET threshold_value = ?, one_time = ?, enabled = 1
            """, (user_id, item_id, alert_type, threshold_value, ot,
                  threshold_value, ot))
            await conn.commit()
    except Exception as e:
        logger.error(f"사용자 알림 설정 저장 실패: {e}")


async def get_user_alerts(
    user_id: int, item_id: str | None = None
) -> list[dict]:
    """사용자의 알림 설정 조회. item_id 없으면 전체."""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            if item_id:
                cursor = await conn.execute("""
                    SELECT s.*, w.item_name
                    FROM user_alert_settings s
                    LEFT JOIN auction_watch_items w ON s.item_id = w.item_id
                    WHERE s.user_id = ? AND s.item_id = ? AND s.enabled = 1
                    ORDER BY s.alert_type
                """, (user_id, item_id))
            else:
                cursor = await conn.execute("""
                    SELECT s.*, w.item_name
                    FROM user_alert_settings s
                    LEFT JOIN auction_watch_items w ON s.item_id = w.item_id
                    WHERE s.user_id = ? AND s.enabled = 1
                    ORDER BY s.item_id, s.alert_type
                """, (user_id,))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"사용자 알림 설정 조회 실패: {e}")
        return []


async def delete_user_alert(
    user_id: int, item_id: str, alert_type: str | None = None
):
    """사용자 알림 삭제. alert_type 없으면 해당 아이템 전체."""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            if alert_type:
                await conn.execute("""
                    DELETE FROM user_alert_settings
                    WHERE user_id = ? AND item_id = ? AND alert_type = ?
                """, (user_id, item_id, alert_type))
            else:
                await conn.execute("""
                    DELETE FROM user_alert_settings
                    WHERE user_id = ? AND item_id = ?
                """, (user_id, item_id))
            await conn.commit()
    except Exception as e:
        logger.error(f"사용자 알림 삭제 실패: {e}")


async def get_all_user_alerts_for_item(item_id: str) -> list[dict]:
    """특정 아이템에 대한 모든 사용자의 알림 설정 조회"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM user_alert_settings
                WHERE item_id = ? AND enabled = 1
            """, (item_id,))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"아이템별 사용자 알림 조회 실패: {e}")
        return []


async def disable_user_alert(
    user_id: int, item_id: str, alert_type: str
):
    """알림 비활성화 (지정가 알림 발동 후)"""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                UPDATE user_alert_settings SET enabled = 0
                WHERE user_id = ? AND item_id = ? AND alert_type = ?
            """, (user_id, item_id, alert_type))
            await conn.commit()
    except Exception as e:
        logger.error(f"사용자 알림 비활성화 실패: {e}")


# ----- 던담 API 일일 사용량 -----

async def get_dundam_daily_usage(date: str) -> int:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT count FROM dundam_daily_usage WHERE date = ?", (date,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"던담 일일 사용량 조회 실패: {e}")
        return 0


async def increment_dundam_daily_usage(date: str, amount: int = 1):
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                INSERT INTO dundam_daily_usage (date, count) VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET count = count + ?
            """, (date, amount, amount))
            await conn.commit()
    except Exception as e:
        logger.error(f"던담 일일 사용량 증가 실패: {e}")


# ----- 던담순위 캐시 -----

async def save_dundam_ranking_cache(entries: list[dict]):
    if not entries:
        return
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.executemany("""
                INSERT OR REPLACE INTO dundam_ranking_cache
                (character_id, server_id, mode, character_name, adventure_name, score, updated_at)
                VALUES (:character_id, :server_id, :mode, :character_name, :adventure_name, :score, :updated_at)
            """, entries)
            await conn.commit()
        logger.info(f"던담순위 캐시 저장: {len(entries)}건")
    except Exception as e:
        logger.error(f"던담순위 캐시 저장 실패: {e}")


async def get_dundam_ranking_cache(mode: str) -> list[dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM dundam_ranking_cache
                WHERE mode = ?
                ORDER BY score DESC
            """, (mode,))
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"던담순위 캐시 조회 실패: {e}")
        return []


async def get_dundam_ranking_cache_timestamp(mode: str) -> str | None:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("""
                SELECT updated_at FROM dundam_ranking_cache
                WHERE mode = ?
                ORDER BY updated_at DESC LIMIT 1
            """, (mode,))
            row = await cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"던담순위 캐시 시간 조회 실패: {e}")
        return None


# ----- 직업별 스킬 옵션 캐시 -----

async def save_job_skill_options(job_key: str, vp_options: str, force_options: str | None):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=9))).isoformat()
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO job_skill_options
                (job_key, skill_vp_options, skill_force_options, updated_at)
                VALUES (?, ?, ?, ?)
            """, (job_key, vp_options, force_options, now))
            await conn.commit()
        logger.info(f"직업 스킬 옵션 캐시 저장: {job_key}")
    except Exception as e:
        logger.error(f"직업 스킬 옵션 캐시 저장 실패: {e}")


async def get_job_skill_options(job_key: str) -> dict | None:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM job_skill_options WHERE job_key = ?", (job_key,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"직업 스킬 옵션 캐시 조회 실패: {e}")
        return None
