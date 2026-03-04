import aiosqlite
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "conversations.db"


async def _get_db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    db = await _get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)
        await db.commit()
    finally:
        await db.close()


async def get_or_create_session(user_id: int, timeout_minutes: int) -> tuple[int, str]:
    """Return (conversation_id, session_id) for the user's active session, or create a new one."""
    db = await _get_db()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        row = await db.execute_fetchall(
            "SELECT id, session_id FROM conversations "
            "WHERE user_id = ? AND last_active > ? "
            "ORDER BY last_active DESC LIMIT 1",
            (user_id, cutoff),
        )
        if row:
            conv_id, session_id = row[0][0], row[0][1]
            await db.execute(
                "UPDATE conversations SET last_active = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), conv_id),
            )
            await db.commit()
            return conv_id, session_id

        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            "INSERT INTO conversations (user_id, session_id, created_at, last_active) VALUES (?, ?, ?, ?)",
            (user_id, session_id, now, now),
        )
        await db.commit()
        return cursor.lastrowid, session_id
    finally:
        await db.close()


async def create_new_session(user_id: int) -> tuple[int, str]:
    """Force-create a new session for the user."""
    db = await _get_db()
    try:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            "INSERT INTO conversations (user_id, session_id, created_at, last_active) VALUES (?, ?, ?, ?)",
            (user_id, session_id, now, now),
        )
        await db.commit()
        return cursor.lastrowid, session_id
    finally:
        await db.close()


async def save_message(conversation_id: int, role: str, content: str):
    db = await _get_db()
    try:
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
    finally:
        await db.close()


async def get_recent_messages(user_id: int, limit: int = 10) -> list[dict]:
    db = await _get_db()
    try:
        rows = await db.execute_fetchall(
            """
            SELECT m.role, m.content, m.timestamp
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.user_id = ?
            ORDER BY m.timestamp DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in reversed(rows)]
    finally:
        await db.close()
