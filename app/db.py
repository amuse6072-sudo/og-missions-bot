# app/db.py
from __future__ import annotations
import os
import aiosqlite
from datetime import datetime
from loguru import logger

try:
    from app.config import settings  # type: ignore
except Exception:
    class _S: ...
    settings = _S()  # type: ignore

# --- storage path -------------------------------------------------------------
def _resolve_storage_dir() -> str:
    env_dir = os.getenv("STORAGE_DIR")
    if env_dir and env_dir.strip():
        return env_dir.strip()
    try:
        v = getattr(settings, "STORAGE_DIR", None)
        if v and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return os.path.join(root, "storage")

_STORAGE_DIR = _resolve_storage_dir()
_DB_PATH = os.path.join(_STORAGE_DIR, "og_missions.db")

# --- helpers -----------------------------------------------------------------
async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(_DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def _table_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table});")
    return {r["name"] for r in await cur.fetchall()}

async def _add_column_if_missing(db: aiosqlite.Connection, table: str, col_sql: str, col_name: str):
    cols = await _table_columns(db, table)
    if col_name not in cols:
        logger.info(f"[DB] MIGRATE: {table} ADD COLUMN {col_name}")
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {col_sql};")

# --- create schema (idempotent) ----------------------------------------------
async def _create_tables(db: aiosqlite.Connection):
    await db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        full_name TEXT,
        karma INTEGER NOT NULL DEFAULT 0,
        rank TEXT NOT NULL DEFAULT '🪙 Бродяга',
        is_admin INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL
    );""")

    await db.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        author_tg_id INTEGER,
        deadline_ts INTEGER,
        difficulty INTEGER NOT NULL DEFAULT 1,
        difficulty_label TEXT NOT NULL DEFAULT '🟢 Лёгкая',
        status TEXT NOT NULL DEFAULT 'OPEN',
        reminder_stage TEXT NOT NULL DEFAULT '',
        extension_count INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        closed_at INTEGER
    );""")

    await db.execute("""
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id INTEGER NOT NULL,
        assignee_tg_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'assigned',
        report_json TEXT,
        created_at INTEGER NOT NULL,
        done_at INTEGER
    );""")

    # исторические «events» (если используются где-то в легаси)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        payload TEXT,
        created_at INTEGER NOT NULL
    );""")

    await db.execute("""
    CREATE TABLE IF NOT EXISTS mission_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id INTEGER,
        actor_tg_id INTEGER,
        kind TEXT NOT NULL,
        payload TEXT,
        created_at INTEGER NOT NULL
    );""")

    await db.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );""")

    await db.execute("""
    CREATE TABLE IF NOT EXISTS karma_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER,
        delta INTEGER NOT NULL,
        reason TEXT,
        created_at INTEGER NOT NULL
    );""")

    await db.execute("""
    CREATE TABLE IF NOT EXISTS appeals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_tg_id INTEGER NOT NULL,
        text TEXT,
        reason TEXT,
        penalty INTEGER NOT NULL,
        status TEXT NOT NULL,  -- open/approved/rejected
        created_at INTEGER NOT NULL
    );""")

# --- migrate schema (safe, idempotent) ---------------------------------------
async def _migrate_tables(db: aiosqlite.Connection):
    # users
    await _add_column_if_missing(db, "users", "username TEXT", "username")
    await _add_column_if_missing(db, "users", "full_name TEXT", "full_name")
    await _add_column_if_missing(db, "users", "karma INTEGER NOT NULL DEFAULT 0", "karma")
    await _add_column_if_missing(db, "users", "rank TEXT NOT NULL DEFAULT '🪙 Бродяга'", "rank")
    await _add_column_if_missing(db, "users", "is_admin INTEGER NOT NULL DEFAULT 0", "is_admin")
    await _add_column_if_missing(db, "users", "active INTEGER NOT NULL DEFAULT 1", "active")
    await _add_column_if_missing(db, "users", "created_at INTEGER NOT NULL DEFAULT 0", "created_at")

    # missions
    await _add_column_if_missing(db, "missions", "author_tg_id INTEGER", "author_tg_id")
    await _add_column_if_missing(db, "missions", "deadline_ts INTEGER", "deadline_ts")
    await _add_column_if_missing(db, "missions", "difficulty INTEGER NOT NULL DEFAULT 1", "difficulty")
    await _add_column_if_missing(db, "missions", "difficulty_label TEXT NOT NULL DEFAULT '🟢 Лёгкая'", "difficulty_label")
    await _add_column_if_missing(db, "missions", "status TEXT NOT NULL DEFAULT 'OPEN'", "status")
    await _add_column_if_missing(db, "missions", "reminder_stage TEXT NOT NULL DEFAULT ''", "reminder_stage")
    await _add_column_if_missing(db, "missions", "extension_count INTEGER NOT NULL DEFAULT 0", "extension_count")
    await _add_column_if_missing(db, "missions", "created_at INTEGER NOT NULL DEFAULT 0", "created_at")
    await _add_column_if_missing(db, "missions", "closed_at INTEGER", "closed_at")

    # assignments
    await _add_column_if_missing(db, "assignments", "assignee_tg_id INTEGER", "assignee_tg_id")
    await _add_column_if_missing(db, "assignments", "status TEXT NOT NULL DEFAULT 'assigned'", "status")
    await _add_column_if_missing(db, "assignments", "report_json TEXT", "report_json")
    await _add_column_if_missing(db, "assignments", "created_at INTEGER NOT NULL DEFAULT 0", "created_at")
    await _add_column_if_missing(db, "assignments", "done_at INTEGER", "done_at")

    # mission_events
    await _add_column_if_missing(db, "mission_events", "mission_id INTEGER", "mission_id")
    await _add_column_if_missing(db, "mission_events", "actor_tg_id INTEGER", "actor_tg_id")
    await _add_column_if_missing(db, "mission_events", "kind TEXT", "kind")
    await _add_column_if_missing(db, "mission_events", "payload TEXT", "payload")
    await _add_column_if_missing(db, "mission_events", "created_at INTEGER NOT NULL DEFAULT 0", "created_at")

    # karma_log
    await _add_column_if_missing(db, "karma_log", "tg_id INTEGER", "tg_id")
    await _add_column_if_missing(db, "karma_log", "delta INTEGER NOT NULL DEFAULT 0", "delta")
    await _add_column_if_missing(db, "karma_log", "reason TEXT", "reason")
    await _add_column_if_missing(db, "karma_log", "created_at INTEGER NOT NULL DEFAULT 0", "created_at")

# --- public -------------------------------------------------------------------
async def ensure_db():
    os.makedirs(_STORAGE_DIR, exist_ok=True)
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _create_tables(db)
        await _migrate_tables(db)

        # backfill timestamps + актив
        now = int(datetime.utcnow().timestamp())
        await db.execute("UPDATE users SET active=1 WHERE active IS NULL;")
        await db.execute("UPDATE users SET created_at=? WHERE created_at IS NULL OR created_at=0;", (now,))
        await db.execute("UPDATE missions SET created_at=? WHERE created_at IS NULL OR created_at=0;", (now,))
        await db.execute("UPDATE assignments SET created_at=? WHERE created_at IS NULL OR created_at=0;", (now,))
        await db.execute("UPDATE mission_events SET created_at=? WHERE created_at IS NULL OR created_at=0;", (now,))
        await db.commit()

    logger.info(f"[DB] initialized at {_DB_PATH}")
