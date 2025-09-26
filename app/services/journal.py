from __future__ import annotations
import json
from typing import Dict, Any, List
from app.db import get_db

ICON = {
    "create": "🆕",
    "done_sent": "✅",
    "admin_cancel": "🗑",
    "late": "💀",
    "overdue": "💀",
    "rank_up": "👑",
    "postpone_1d": "⏳",
}

async def _table_exists(db, name: str) -> bool:
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return await cur.fetchone() is not None

async def _assignees_str(db, mission_id: int) -> str:
    sql = """
      SELECT '@'||COALESCE(u.username, 'id'||a.assignee_tg_id) AS u
      FROM assignments a
      LEFT JOIN users u ON u.tg_id = a.assignee_tg_id
      WHERE a.mission_id=?
    """
    cur = await db.execute(sql, (mission_id,))
    rows = [r["u"] for r in await cur.fetchall()]
    return ", ".join(rows) if rows else "не назначен"

async def _mission_title(db, mission_id: int) -> str:
    cur = await db.execute("SELECT title FROM missions WHERE id=?", (mission_id,))
    r = await cur.fetchone()
    return r["title"] if r else "без названия"

async def recent_events_text(limit: int = 15) -> str:
    """
    Универсальный журнал:
    - если есть таблица mission_events (старый формат) — читаем из неё;
    - иначе используем events(kind, payload, created_at) и вытягиваем mission_id из JSON payload.
    """
    db = await get_db()
    try:
        if await _table_exists(db, "mission_events"):
            sql = """
            WITH ass AS (
              SELECT a.mission_id,
                     GROUP_CONCAT('@'||COALESCE(u.username, 'id'||a.assignee_tg_id), ', ') AS assignees
              FROM assignments a
              LEFT JOIN users u ON u.tg_id = a.assignee_tg_id
              GROUP BY a.mission_id
            )
            SELECT e.kind, e.payload, e.created_at,
                   COALESCE('@'||u.username, 'кто-то') AS actor,
                   m.title AS m_title,
                   ass.assignees
            FROM mission_events e
            LEFT JOIN missions m ON m.id = e.mission_id
            LEFT JOIN users u ON u.tg_id = e.actor_tg_id
            LEFT JOIN ass ON ass.mission_id = e.mission_id
            ORDER BY e.id DESC
            LIMIT ?
            """
            cur = await db.execute(sql, (limit,))
            rows = await cur.fetchall()
            if not rows:
                return "Журнал пуст. Двигай движ!"
            out: List[str] = ["📜 <b>Журнал</b>"]
            for r in rows:
                kind = str(r["kind"]).lower()
                icon = ICON.get(kind, "•")
                title = r["m_title"] or "без названия"
                who = r["actor"] or "кто-то"
                ass = r["assignees"] or "не назначен"
                if kind == "create":
                    out.append(f"{icon} {who} → {ass}: «{title}»")
                elif kind == "done_sent":
                    out.append(f"{icon} {who} сдал отчёт по «{title}»")
                elif kind in {"admin_cancel"}:
                    out.append(f"{icon} «{title}» отменена админом")
                elif kind in {"late","overdue"}:
                    out.append(f"{icon} Просрочка по «{title}»")
                elif kind == "rank_up":
                    out.append(f"{icon} {who} апнул ранг")
                else:
                    out.append(f"{icon} {who} • {kind} • «{title}»")
            return "\n".join(out)

        # — Новый формат (events с JSON payload) —
        cur = await db.execute(
            "SELECT kind, payload, created_at FROM events ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = await cur.fetchall()
        if not rows:
            return "Журнал пуст. Двигай движ!"

        out: List[str] = ["📜 <b>Журнал</b>"]
        for r in rows:
            kind = (r["kind"] or "").lower()
            icon = ICON.get(kind, "•")
            payload: Dict[str, Any] = {}
            try:
                payload = json.loads(r["payload"] or "{}")
            except Exception:
                payload = {}
            mission_id = payload.get("mission_id")
            actor_tg_id = payload.get("actor_tg_id") or payload.get("by_tg_id")

            title = await _mission_title(db, int(mission_id)) if mission_id else "без названия"
            ass = await _assignees_str(db, int(mission_id)) if mission_id else "—"

            if kind == "create":
                who = payload.get("author_tg_id") or actor_tg_id or "кто-то"
                who_txt = f"@id{who}" if isinstance(who, int) else str(who)
                out.append(f"{icon} {who_txt} → {ass}: «{title}»")
            elif kind == "done_sent":
                who = actor_tg_id or "кто-то"
                who_txt = f"@id{who}" if isinstance(who, int) else str(who)
                out.append(f"{icon} {who_txt} сдал отчёт по «{title}»")
            elif kind in {"admin_cancel"}:
                out.append(f"{icon} «{title}» отменена админом")
            elif kind in {"late","overdue"}:
                out.append(f"{icon} Просрочка по «{title}»")
            elif kind == "postpone_1d":
                out.append(f"{icon} Дедлайн «{title}» продлён на сутки (−1 карма)")
            elif kind == "rank_up":
                out.append(f"{icon} Ап ранга")
            else:
                out.append(f"{icon} {kind} • «{title}»")
        return "\n".join(out)
    finally:
        await db.close()
