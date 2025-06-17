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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS registrations (
                    user_id INTEGER NOT NULL,
                    character_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, character_id),
                    FOREIGN KEY(character_id) REFERENCES characters(character_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS item_cache (
                    item_id TEXT PRIMARY KEY,
                    item_available_level INTEGER NOT NULL
                )
            """)
            await conn.commit()
        logger.info("DB 초기화 완료")
    except Exception as e:
        logger.error(f"DB 초기화 실패: {e}")


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


# ---------------------------
# 아이템 캐시 관련 함수 추가
# ---------------------------

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
