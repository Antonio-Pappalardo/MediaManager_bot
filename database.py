import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger(__name__)

DB_NAME = "bot_database.db"
HASH_THRESHOLD = 5

_db_connection: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Provides a persistent database connection with WAL mode and foreign keys enabled."""
    global _db_connection

    # Double-checked locking to prevent race conditions during initial connection setup
    if _db_connection is None:
        async with _db_lock:
            if _db_connection is None:
                conn = await aiosqlite.connect(DB_NAME)
                try:
                    # SQLite disables foreign keys by default per-connection; enable them explicitly
                    await conn.execute("PRAGMA foreign_keys = ON;")
                    await conn.execute("PRAGMA journal_mode = WAL;")
                    await conn.execute("PRAGMA synchronous = NORMAL;")
                    await conn.execute("PRAGMA busy_timeout = 5000;")
                except Exception:
                    await conn.close()
                    raise
                _db_connection = conn

    yield _db_connection


async def close_database() -> None:
    """Closes the persistent database connection cleanly on shutdown."""
    global _db_connection
    async with _db_lock:
        if _db_connection is not None:
            await _db_connection.close()
            _db_connection = None
            logger.info("Database connection closed cleanly.")


async def initialize_database() -> None:
    """Creates the database tables and indexes if they do not exist."""
    async with get_db() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS authorized_groups (
                group_id TEXT PRIMARY KEY,
                group_name TEXT NOT NULL
            )
        ''')

        # INTEGER PRIMARY KEY aliases SQLite's internal rowid (auto-increments without AUTOINCREMENT overhead)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS saved_files (
                id INTEGER PRIMARY KEY,
                group_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                unique_id TEXT NOT NULL,
                media_hash TEXT,
                message_id INTEGER NOT NULL,
                FOREIGN KEY(group_id) REFERENCES authorized_groups(group_id) ON DELETE CASCADE
            )
        ''')

        await db.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_group_unique 
            ON saved_files(group_id, unique_id)
        ''')

        # Covering index to avoid table lookups during perceptual hash scans
        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_group_mediatype_hash 
            ON saved_files(group_id, media_type, media_hash, message_id)
        ''')

        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_group_message 
            ON saved_files(group_id, message_id)
        ''')

        await db.commit()
        logger.info("Database initialized successfully with WAL mode, schema, and indexes.")


async def check_id(group_id: str, unique_id: str) -> int | None:
    """Checks if the exact Telegram unique ID already exists in the database."""
    async with get_db() as db:
        async with db.execute(
            "SELECT message_id FROM saved_files WHERE group_id = ? AND unique_id = ?",
            (group_id, unique_id)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None


async def check_hash(group_id: str, current_hash_str: str, media_type: str) -> int | None:
    """Compares the incoming perceptual hash against stored hashes using bitwise XOR Hamming distance."""
    try:
        current_hash_int = int(current_hash_str, 16)
        current_len = len(current_hash_str)
    except ValueError:
        logger.error("Malformed incoming hash string: %s", current_hash_str)
        return None

    async with get_db() as db:
        async with db.execute(
            "SELECT media_hash, message_id FROM saved_files WHERE group_id = ? AND media_type = ?",
            (group_id, media_type)
        ) as cursor:
            # Linear scan O(N): XOR and bit_count() are native, though iteration runs in Python.
            # Fast enough for typical group sizes; massive scale would require BK-trees.
            async for db_hash_str, message_id in cursor:
                if not db_hash_str or len(db_hash_str) != current_len:
                    continue

                try:
                    distance = (current_hash_int ^ int(db_hash_str, 16)).bit_count()
                except ValueError:
                    logger.warning("Corrupted hash in database, skipping: %s", db_hash_str)
                    continue

                if distance <= HASH_THRESHOLD:
                    return message_id
    return None


async def add_to_database(
    group_id: str,
    media_type: str,
    unique_id: str,
    media_hash: str,
    message_id: int
) -> None:
    """Saves a new media record into the database, ignoring concurrent duplicates."""
    async with get_db() as db:
        await db.execute('''
            INSERT OR IGNORE INTO saved_files (group_id, media_type, unique_id, media_hash, message_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (group_id, media_type, unique_id, media_hash, message_id))
        await db.commit()


async def update_original_message(group_id: str, old_message_id: int, new_message_id: int) -> None:
    """Updates the message ID of a stored file if the original post was replaced or deleted."""
    async with get_db() as db:
        await db.execute('''
            UPDATE saved_files 
            SET message_id = ? 
            WHERE group_id = ? AND message_id = ?
        ''', (new_message_id, group_id, old_message_id))
        await db.commit()


async def authorize_group(group_id: str, group_name: str = "Unknown") -> None:
    """Adds or updates a group in the authorized list without triggering DELETE cascades."""
    async with get_db() as db:
        # Use DO UPDATE instead of INSERT OR REPLACE to avoid deleting and cascading child records
        await db.execute('''
            INSERT INTO authorized_groups (group_id, group_name) 
            VALUES (?, ?)
            ON CONFLICT(group_id) DO UPDATE SET 
            group_name = CASE 
                WHEN excluded.group_name != 'Unknown' THEN excluded.group_name 
                ELSE authorized_groups.group_name 
            END
        ''', (group_id, group_name))
        await db.commit()


async def revoke_group(group_id: str) -> None:
    """Removes a group from the authorized list and deletes its associated files via CASCADE."""
    async with get_db() as db:
        await db.execute("DELETE FROM authorized_groups WHERE group_id = ?", (group_id,))
        await db.commit()


async def check_permission_and_name(group_id: str) -> str | None:
    """Checks if a group is authorized and returns its stored name."""
    async with get_db() as db:
        async with db.execute(
            "SELECT group_name FROM authorized_groups WHERE group_id = ?",
            (group_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None


async def get_authorized_groups() -> list[tuple[str, str]]:
    """Retrieves a list of all authorized groups as (group_id, group_name) tuples."""
    async with get_db() as db:
        async with db.execute("SELECT group_id, group_name FROM authorized_groups") as cursor:
            rows = await cursor.fetchall()
            return [(row[0], row[1]) for row in rows]
