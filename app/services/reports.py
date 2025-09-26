from __future__ import annotations
from typing import List
from app.db import get_db
from datetime import datetime
from dateutil import tz

def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=tz.gettz("Europe/Kyiv")).strftime("%H:%M")
    except Exception:
        return "-"

async def build_report_messages() -> List[str]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT title, deadline_ts FROM missions WHERE status IN ('OPEN','IN_PROGRESS') ORDER BY deadline_ts IS NULL, deadline_ts ASC LIMIT 10")
        opens = await cur.fetchall()
        cur2 = await db.execute("SELECT username, karma FROM users ORDER BY karma DESC LIMIT 3")
        top = await cur2.fetchall()
        parts = []
        if opens:
            items = "\n".join([f"• {x['title']} — {_fmt_ts(x['deadline_ts'])}" for x in opens])
            parts.append("🔥 Горящие задачи:\n" + items)
        if top:
            t3 = "\n".join([f"{i+1}. @{x['username']} — {x['karma']}" for i, x in enumerate(top)])
            parts.append("🏆 Топ-3 по карме:\n" + t3)
        return parts
    finally:
        await db.close()
