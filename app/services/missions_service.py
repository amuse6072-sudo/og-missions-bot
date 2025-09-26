from __future__ import annotations
from typing import List, Optional, Tuple, Dict
import json

from aiogram.types import User
from loguru import logger

from app.db import get_db
from app.utils.time import now_ts
from app.services import karma as karma_svc
from app.config import settings

STATUS = {
    "DRAFT": "Черновик",
    "OPEN": "Опубликована",
    "IN_PROGRESS": "На исполнении",
    "WAIT_REPORT": "Ожидает отчёта",
    "REVIEW": "На проверке",
    "DONE": "Завершена",
    "REWORK": "Доработка",
    "CANCELLED": "Отменена",
    "OVERDUE": "Просрочена",
    "CANCELLED_ADMIN": "Удалена админом",
    "DECLINED": "Отказ",
}

# ───────────────── USERS ─────────────────

async def ensure_user(u: User) -> None:
    if not u:
        return
    db = await get_db()
    try:
        cur = await db.execute("SELECT id FROM users WHERE tg_id=?", (u.id,))
        row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO users (tg_id, username, full_name, is_admin, karma, rank, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (u.id, (u.username or "").lstrip("@"), u.full_name or "", 0, 0, "🪙 Бродяга", now_ts())
            )
        else:
            await db.execute(
                "UPDATE users SET username=?, full_name=? WHERE tg_id=?",
                ((u.username or "").lstrip("@"), u.full_name or "", u.id)
            )
        await db.commit()
    finally:
        await db.close()

async def is_admin(tg_id: int) -> bool:
    db = await get_db()
    try:
        cur = await db.execute("SELECT is_admin FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        return bool(row and row["is_admin"])
    finally:
        await db.close()

async def set_admin(tg_id: int, flag: bool) -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE users SET is_admin=? WHERE tg_id=?", (1 if flag else 0, tg_id))
        await db.commit()
    finally:
        await db.close()

async def upsert_user_manual(tg_id: int | None, username: str | None, full_name: str | None) -> None:
    uname = (username or "").lstrip("@")
    db = await get_db()
    try:
        if tg_id:
            cur = await db.execute("SELECT id FROM users WHERE tg_id=?", (tg_id,))
            row = await cur.fetchone()
            if row:
                await db.execute(
                    "UPDATE users SET username=?, full_name=? WHERE tg_id=?",
                    (uname, full_name or "", tg_id)
                )
            else:
                await db.execute(
                    "INSERT INTO users (tg_id, username, full_name, is_admin, karma, rank, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (tg_id, uname, full_name or "", 0, 0, "🪙 Бродяга", now_ts())
                )
        else:
            cur = await db.execute("SELECT id FROM users WHERE username=?", (uname,))
            row = await cur.fetchone()
            if row:
                await db.execute("UPDATE users SET full_name=? WHERE username=?", (full_name or "", uname))
            else:
                await db.execute(
                    "INSERT INTO users (username, full_name, is_admin, karma, rank, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (uname, full_name or "", 0, 0, "🪙 Бродяга", now_ts())
                )
        await db.commit()
    finally:
        await db.close()

async def delete_user(tg_id: int | None = None, username: str | None = None) -> int:
    db = await get_db()
    try:
        if tg_id is None and username:
            cur = await db.execute("SELECT tg_id FROM users WHERE username=?", (username.lstrip("@"),))
            row = await cur.fetchone()
            tg_id = int(row["tg_id"]) if row and row["tg_id"] else None
        if tg_id is None:
            return 0
        await db.execute("DELETE FROM assignments WHERE assignee_tg_id=?", (tg_id,))
        cur = await db.execute("DELETE FROM users WHERE tg_id=?", (tg_id,))
        await db.commit()
        return cur.rowcount or 0
    finally:
        await db.close()

async def find_user_by_username(username: str) -> Optional[Dict]:
    db = await get_db()
    try:
        u = username.lstrip("@")
        cur = await db.execute("SELECT * FROM users WHERE username=?", (u,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()

async def find_user_by_name_prefix(name: str) -> Optional[Dict]:
    if not name:
        return None
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM users WHERE LOWER(full_name) LIKE ? ORDER BY LENGTH(full_name) ASC LIMIT 1",
            (name.lower() + "%",)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()

async def list_users(page: int = 0, page_size: int = 8, pattern: str | None = None):
    db = await get_db()
    try:
        where = ""
        args: list = []
        if pattern:
            where = "WHERE (LOWER(username) LIKE ? OR LOWER(full_name) LIKE ?)"
            p = f"%{pattern.lower()}%"
            args += [p, p]
        count_sql = f"SELECT COUNT(*) c FROM users {where}"
        cur = await db.execute(count_sql, args)
        total = (await cur.fetchone())["c"]
        offset = page * page_size
        cur2 = await db.execute(
            f"SELECT tg_id, username, full_name FROM users {where} "
            f"ORDER BY full_name ASC, username ASC LIMIT ? OFFSET ?",
            args + [page_size, offset]
        )
        rows = [dict(r) for r in await cur2.fetchall()]
        return rows, total
    finally:
        await db.close()

async def list_users_with_stats(page: int = 0, page_size: int = 8, pattern: str | None = None) -> Tuple[List[Dict], int]:
    db = await get_db()
    try:
        where = ""
        args: list = []
        if pattern:
            where = "WHERE (LOWER(u.username) LIKE ? OR LOWER(u.full_name) LIKE ?)"
            p = f"%{pattern.lower()}%"
            args += [p, p]
        cur = await db.execute(f"SELECT COUNT(*) c FROM users u {where}", args)
        total = int((await cur.fetchone())["c"])
        offset = page * page_size
        cur2 = await db.execute(
            f"""
            SELECT
                u.tg_id, u.username, u.full_name, COALESCE(u.karma,0) AS karma,
                (
                    SELECT COUNT(1)
                    FROM assignments a
                    JOIN missions m ON m.id = a.mission_id
                    WHERE a.assignee_tg_id = u.tg_id
                      AND COALESCE(m.status,'') NOT IN ('DONE','CANCELLED','CANCELLED_ADMIN')
                ) AS active_count
            FROM users u
            {where}
            ORDER BY u.full_name ASC, u.username ASC
            LIMIT ? OFFSET ?
            """,
            args + [page_size, offset]
        )
        rows = [dict(r) for r in await cur2.fetchall()]
        return rows, total
    finally:
        await db.close()

# ───────────────── MISSIONS ─────────────────

async def create_mission(
    title: str,
    description: str,
    author_tg_id: int,
    assignees: List[int],
    deadline_ts: Optional[int],
    difficulty: int,
    difficulty_label: str
) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO missions (title, description, author_tg_id, deadline_ts, difficulty, difficulty_label, status, reminder_stage, extension_count, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, description, author_tg_id, deadline_ts, difficulty, difficulty_label, "OPEN", "", 0, now_ts())
        )
        mid = cur.lastrowid
        for a in assignees:
            await db.execute(
                "INSERT INTO assignments (mission_id, assignee_tg_id, created_at) VALUES (?,?,?)",
                (mid, a, now_ts())
            )
        await db.execute(
            "INSERT INTO events (kind, payload, created_at) VALUES (?,?,?)",
            ("create", json.dumps({"mission_id": mid, "author_tg_id": author_tg_id}, ensure_ascii=False), now_ts())
        )
        await db.commit()
        return mid
    finally:
        await db.close()

async def mission_summary(mission_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM missions WHERE id=?", (mission_id,))
        m = await cur.fetchone()
        if not m:
            return None
        cur2 = await db.execute("SELECT assignee_tg_id FROM assignments WHERE mission_id=?", (mission_id,))
        assignees = [dict(x) for x in await cur2.fetchall()]
        return {"mission": dict(m), "assignees": assignees}
    finally:
        await db.close()

async def set_status(mission_id: int, status: str) -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE missions SET status=? WHERE id=?", (status, mission_id))
        await db.commit()
    finally:
        await db.close()

async def add_event(kind: str, payload: dict) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO events (kind, payload, created_at) VALUES (?,?,?)",
            (kind, json.dumps(payload, ensure_ascii=False), now_ts())
        )
        await db.commit()
        return int(cur.lastrowid or 0)
    finally:
        await db.close()

async def list_missions_page(page: int, page_size: int = 10) -> Tuple[List[Dict], int]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) AS cnt FROM missions")
        total = int((await cur.fetchone())["cnt"])
        cur = await db.execute(
            """
            SELECT m.id, m.title, m.status, m.deadline_ts, m.author_tg_id, m.difficulty,
                   a.assignee_tg_id
            FROM missions m
            LEFT JOIN assignments a ON a.mission_id = m.id
            ORDER BY m.id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, page * page_size)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows], total
    finally:
        await db.close()

async def mark_done(mission_id: int, actor_tg_id: int) -> None:
    await set_status(mission_id, "REVIEW")
    await add_event("done_sent", {"mission_id": mission_id, "actor_tg_id": actor_tg_id})

# ───────────────── REMINDERS / PENALTIES ─────────────────

async def get_assignees_tg(mission_id: int) -> List[int]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT assignee_tg_id FROM assignments WHERE mission_id=?", (mission_id,))
        return [int(r["assignee_tg_id"]) for r in await cur.fetchall()]
    finally:
        await db.close()

async def set_reminder_stage(mission_id: int, stage: str) -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE missions SET reminder_stage=? WHERE id=?", (stage, mission_id))
        await db.commit()
    finally:
        await db.close()

# legacy: +1 день с фиксированным штрафом -1
async def postpone_one_day(mission_id: int, by_tg_id: int) -> Tuple[bool, str, Optional[int]]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT deadline_ts, extension_count, title FROM missions WHERE id=?", (mission_id,))
        m = await cur.fetchone()
        if not m:
            return False, "Миссия не найдена.", None
        if int(m["extension_count"] or 0) >= 1:
            return False, "Продление уже использовано.", None
        base = int(m["deadline_ts"] or now_ts())
        new_deadline = base + 24 * 3600
        await db.execute(
            "UPDATE missions SET deadline_ts=?, extension_count=?, reminder_stage='' WHERE id=?",
            (new_deadline, 1, mission_id)
        )
        await db.commit()
        cur2 = await db.execute("SELECT assignee_tg_id FROM assignments WHERE mission_id=?", (mission_id,))
        for r in await cur2.fetchall():
            await karma_svc.add_karma_tg(int(r["assignee_tg_id"]), -1, "Продление дедлайна на сутки")
        await add_event("postpone_1d", {"mission_id": mission_id, "by_tg_id": by_tg_id, "new_deadline": new_deadline})
        return True, "Дедлайн продлён на сутки. -1 к карме исполнителю.", new_deadline
    finally:
        await db.close()

# новый перенос: 1/2/3 дня с штрафами 0/-1/-2
async def postpone_days(mission_id: int, days: int, by_tg_id: int, penalty: int) -> Tuple[bool, str, Optional[int]]:
    days = max(1, min(3, int(days or 1)))
    db = await get_db()
    try:
        cur = await db.execute("SELECT deadline_ts, title, extension_count FROM missions WHERE id=?", (mission_id,))
        m = await cur.fetchone()
        if not m:
            return False, "Миссия не найдена.", None
        base = int(m["deadline_ts"] or now_ts())
        new_deadline = base + days * 24 * 3600
        await db.execute(
            "UPDATE missions SET deadline_ts=?, extension_count=COALESCE(extension_count,0)+1, reminder_stage='' WHERE id=?",
            (new_deadline, mission_id)
        )
        await db.commit()
        if penalty != 0:
            cur2 = await db.execute("SELECT assignee_tg_id FROM assignments WHERE mission_id=?", (mission_id,))
            for r in await cur2.fetchall():
                await karma_svc.add_karma_tg(int(r["assignee_tg_id"]), penalty, f"Перенос дедлайна на {days} дн.")
        await add_event("postpone_days", {
            "mission_id": mission_id, "by_tg_id": by_tg_id, "days": days, "new_deadline": new_deadline, "penalty": penalty
        })
        return True, f"Дедлайн +{days} дн. ({penalty:+d} кармы).", new_deadline
    finally:
        await db.close()

async def mark_overdue_and_penalize(mission_id: int) -> int:
    db = await get_db()
    try:
        cur = await db.execute("SELECT extension_count FROM missions WHERE id=?", (mission_id,))
        m = await cur.fetchone()
        if not m:
            return 0
        ext = int(m["extension_count"] or 0)
        penalty = -4 if ext >= 1 else -3
        cur2 = await db.execute("SELECT assignee_tg_id FROM assignments WHERE mission_id=?", (mission_id,))
        for r in await cur2.fetchall():
            await karma_svc.add_karma_tg(int(r["assignee_tg_id"]), penalty, "Просрочка миссии")
        await db.execute("UPDATE missions SET status='OVERDUE', reminder_stage='overdue' WHERE id=?", (mission_id,))
        await db.commit()
        await add_event("overdue", {"mission_id": mission_id, "penalty": penalty})
        return penalty
    finally:
        await db.close()

# ───────────────── APPEALS / REVIEW ─────────────────

def _admin_target() -> Optional[int]:
    return settings.REPORT_CHAT_ID or settings.ADMIN_USER_ID

async def create_appeal(author_tg_id: int, original_text: str, violation: str, penalty: int) -> int:
    """Сохраняем апелляцию как событие и возвращаем её id."""
    payload = {
        "author_tg_id": author_tg_id,
        "original": original_text,
        "violation": violation,
        "penalty": penalty,
    }
    return await add_event("appeal", payload)

async def approve_report(mid: int, reviewer_tg: int) -> int:
    db = await get_db()
    try:
        cur = await db.execute("SELECT difficulty FROM missions WHERE id=?", (mid,))
        m = await cur.fetchone()
        if not m:
            return 0
        diff = int(m["difficulty"] or 1)
        cur2 = await db.execute("SELECT assignee_tg_id FROM assignments WHERE mission_id=?", (mid,))
        ass = [int(r["assignee_tg_id"]) for r in await cur2.fetchall()]
        for tg in ass:
            await karma_svc.add_karma_tg(tg, +diff, "Отчёт принят")
        await db.execute("UPDATE missions SET status='DONE', closed_at=? WHERE id=?", (now_ts(), mid))
        await db.commit()
        await add_event("review_approved", {"mission_id": mid, "by": reviewer_tg, "bonus": diff})
        return diff
    finally:
        await db.close()

async def reject_report(mid: int, reviewer_tg: int, reason: str | None = None) -> None:
    await set_status(mid, "REWORK")
    await add_event("review_rejected", {"mission_id": mid, "by": reviewer_tg, "reason": reason or ""})
