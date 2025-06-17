import aiosqlite
from pathlib import Path

DB_PATH = Path("data/characters.db")

async def init_db():
    """DB 파일 및 테이블을 비동기로 초기화합니다."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        await conn.commit()


async def save_character(character: dict):
    """캐릭터 정보를 저장하거나 갱신합니다."""
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


async def register_character(user_id: int, character_id: str):
    """사용자가 캐릭터를 등록합니다."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            INSERT OR IGNORE INTO registrations (user_id, character_id)
            VALUES (?, ?)
        """, (user_id, character_id))
        await conn.commit()


async def get_characters_by_adventure_name(adventure_name: str) -> list[dict]:
    """모험단 이름으로 캐릭터를 조회합니다."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT * FROM characters
            WHERE adventure_name = ?
        """, (adventure_name,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_characters_by_user(user_id: int) -> list[dict]:
    """특정 사용자가 등록한 캐릭터 목록을 조회합니다."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT c.*
            FROM characters c
            JOIN registrations r ON c.character_id = r.character_id
            WHERE r.user_id = ?
        """, (user_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
