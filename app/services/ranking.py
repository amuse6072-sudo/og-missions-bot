from __future__ import annotations
from typing import List, Tuple, Optional, Dict
import re
from app.db import get_db

# Бейзлайн рангов: каждые +100 кармы — +1 ступень.
# <0 карма — спец-ранг.
RANK_NAMES = [
    "🪙 Бродяга",           # 0..99
    "🚬 Шпана",             # 100..199
    "🧢 Дворовой",          # 200..299
    "💼 Бывалый",           # 300..399
    "🩸 Авторитет",         # 400..499
    "💿 Mixtape Hustler",   # 500..599
    "🔥 Уличный OG",        # 600..699
    "💎 Платиновый Игрок",  # 700..799
    "🦍 Big Ape",           # 800..899
    "👑 Король Квартала",   # 900..999
    "🕶 Легенда Улиц",      # 1000+
]
NEGATIVE_RANK = "😈 АХУЕВШИЙ ТИП"

def rank_for(karma: int | float | None) -> str:
    k = int(karma or 0)
    if k < 0:
        return NEGATIVE_RANK
    idx = k // 100
    if idx >= len(RANK_NAMES):
        return RANK_NAMES[-1]
    return RANK_NAMES[idx]

def next_threshold(karma: int | float | None) -> Optional[Tuple[int, str]]:
    k = int(karma or 0)
    if k < 0:
        return (0, RANK_NAMES[0])
    idx = k // 100
    nxt = (idx + 1) * 100
    if idx >= len(RANK_NAMES) - 1:
        return None
    return nxt, RANK_NAMES[idx + 1]

def _display_name(u: Dict) -> str:
    if u.get("username"):
        return f"@{u['username']}"
    if u.get("full_name"):
        return u["full_name"]
    return f"id{u.get('tg_id')}"

def _format_place(i: int) -> str:
    return f"{i:>2}."

async def profile_text(tg_id: int) -> str:
    db = await get_db()
    try:
        cur = await db.execute("SELECT tg_id, username, full_name, karma FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if not row:
            return "Профиль не найден. Нажми старт или попроси админа добавить тебя."
        u = dict(row)
        k = int(u.get("karma") or 0)
        rname = rank_for(k)
        nxt = next_threshold(k)
        if nxt:
            need_pts, nxt_name = nxt
            need = max(0, need_pts - k)
            # прогресс внутри текущей сотни
            base = (k // 100) * 100
            filled = max(0, min(10, (k - base) // 10))
            bar = "█" * filled + "─" * (10 - filled)
            return (
                f"{rname} {_display_name(u)}\n"
                f"Карма: <b>{k}</b>\n"
                f"До ранга «{nxt_name}»: {need}\n"
                f"[{bar}]  ({k - base}/100)"
            )
        else:
            return (
                f"{rname} {_display_name(u)}\n"
                f"Карма: <b>{k}</b>\n"
                f"Ты на вершине — дальше только легенда."
            )
    finally:
        await db.close()

async def leaderboard_text(limit: int = 15) -> str:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT tg_id, username, full_name, karma FROM users ORDER BY karma DESC, tg_id ASC LIMIT ?",
            (limit,)
        )
        top = [dict(r) for r in await cur.fetchall()]

        cur2 = await db.execute(
            "SELECT tg_id, username, full_name, karma FROM users ORDER BY karma ASC, tg_id ASC LIMIT 1"
        )
        last = await cur2.fetchone()

        if not top:
            return "Табло пустое — пока никто не отметился."

        lines: List[str] = ["<b>Табло кармы</b>"]
        for i, u in enumerate(top, start=1):
            lines.append(f"{_format_place(i)} {rank_for(u['karma'])} {_display_name(u)} — {u['karma']}")

        if last:
            last_d = dict(last)
            lines.append("\n— — —")
            lines.append(f"Внизу: {rank_for(last_d['karma'])} {_display_name(last_d)} — {last_d['karma']}")
        return "\n".join(lines)
    finally:
        await db.close()

# Обращение по рангу для «уличного» ассистента
def _rank_to_vocative(rank: str) -> str:
    r = re.sub(r"^[^\w]+", "", rank).lower()
    if "ахуе" in r:
        return "ахуевший тип"
    # упрощённые формы
    repl = {
        "бродяга": "бродяга",
        "шпана": "шпана",
        "дворовой": "дворовой",
        "бывалый": "бывалый",
        "авторитет": "авторитет",
        "уличный og": "уличный og",
        "король квартала": "король квартала",
        "легенда улиц": "легенда улиц",
        "god mode og": "god mode og",
        "mixtape hustler": "хастлер",
        "платиновый игрок": "платиновый игрок",
        "big ape": "big ape",
    }
    for k, v in repl.items():
        if k in r:
            return v
    return r

async def address_for(tg_id: int) -> str:
    db = await get_db()
    try:
        cur = await db.execute("SELECT username, full_name, karma FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if not row:
            return f"эй, боец id{tg_id}"
        u = dict(row)
        k = int(u.get("karma") or 0)
        voc = _rank_to_vocative(rank_for(k))
        name = u.get("full_name") or (f"@{u['username']}" if u.get("username") else f"id{tg_id}")
        return f"эй, {voc} {name}"
    finally:
        await db.close()
