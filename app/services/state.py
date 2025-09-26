from __future__ import annotations
import json
from typing import Any, Dict, Optional

from app.db import get_db

_KEY = "state:{uid}"

async def set_state(tg_id: int, value: Dict[str, Any]) -> None:
    key = _KEY.format(uid=tg_id)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False))
        )
        await db.commit()
    finally:
        await db.close()

async def get_state(tg_id: int) -> Dict[str, Any]:
    key = _KEY.format(uid=tg_id)
    db = await get_db()
    try:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        if not row:
            return {}
        return json.loads(row["value"])
    finally:
        await db.close()

async def clear_state(tg_id: int) -> None:
    key = _KEY.format(uid=tg_id)
    db = await get_db()
    try:
        await db.execute("DELETE FROM settings WHERE key=?", (key,))
        await db.commit()
    finally:
        await db.close()

async def update_state(tg_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    data = await get_state(tg_id)
    data.update(patch or {})
    await set_state(tg_id, data)
    return data

async def pop_state_key(tg_id: int, key: str, default: Optional[Any] = None) -> Any:
    data = await get_state(tg_id)
    val = data.pop(key, default)
    await set_state(tg_id, data)
    return val
