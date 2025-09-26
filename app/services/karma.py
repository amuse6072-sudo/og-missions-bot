from __future__ import annotations
from app.db import get_db
from app.services.ranking import rank_for
from app.utils.time import now_ts

async def _recompute_rank_by_tg(tg_id: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT karma FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if row is not None:
            new_rank = rank_for(int(row["karma"] or 0))
            await db.execute("UPDATE users SET rank=? WHERE tg_id=?", (new_rank, tg_id))
            await db.commit()
    finally:
        await db.close()

async def add_karma_tg(tg_id: int, delta: int, reason: str):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO karma_log (tg_id, delta, reason, created_at) VALUES (?,?,?,?)",
            (tg_id, delta, reason, now_ts())
        )
        await db.execute("UPDATE users SET karma = COALESCE(karma,0) + ? WHERE tg_id=?", (delta, tg_id))
        await db.commit()
    finally:
        await db.close()
    await _recompute_rank_by_tg(tg_id)

async def add_karma_by_username(username_at: str, delta: int, reason: str) -> int:
    username = username_at[1:] if username_at.startswith("@") else username_at
    db = await get_db()
    try:
        cur = await db.execute("SELECT tg_id, karma FROM users WHERE username=?", (username,))
        row = await cur.fetchone()
        if not row:
            raise RuntimeError("Пользователь не найден")
        tg_id = int(row["tg_id"])
        await add_karma_tg(tg_id, delta, reason)
        cur2 = await db.execute("SELECT karma FROM users WHERE tg_id=?", (tg_id,))
        row2 = await cur2.fetchone()
        return int(row2["karma"] or 0)
    finally:
        await db.close()

async def reset_all_karma():
    db = await get_db()
    try:
        await db.execute("UPDATE users SET karma=0, rank='🪙 Бродяга'")
        await db.execute("DELETE FROM karma_log")
        await db.commit()
    finally:
        await db.close()

# штраф за отказ (бытовые — -3..-5; прочие — -2)
async def apply_decline_penalty(tg_id: int, difficulty: int, household: bool) -> int:
    if household:
        if difficulty <= 1:
            pen = -3
        elif difficulty == 2:
            pen = -4
        else:
            pen = -5
    else:
        pen = -2
    await add_karma_tg(tg_id, pen, "Отказ от миссии")
    return pen
