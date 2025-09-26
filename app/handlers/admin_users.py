from __future__ import annotations

import contextlib
import re
from typing import List, Dict, Optional

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from app.db import get_db
from app.services.missions_service import is_admin as is_admin_fn
from app.services.state import get_state, update_state, pop_state_key

router = Router()

PAGE_SIZE = 10

# ───────────────── username utils ─────────────────
_username_rx = re.compile(r"^@?([A-Za-z0-9_]{3,32})$")

def _norm_username(s: str) -> Optional[str]:
    s = (s or "").strip()
    m = _username_rx.match(s)
    if not m:
        return None
    return m.group(1).lower()

# ───────────────── DB helpers ────────────────────
async def _ensure_users_schema() -> None:
    """Гарантируем, что в users есть колонка active и индекс по username."""
    db = await get_db()
    try:
        cur = await db.execute("PRAGMA table_info(users)")
        cols = [r["name"] for r in await cur.fetchall()]
        if "active" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN active INTEGER DEFAULT 1")
            await db.commit()
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        await db.commit()
    finally:
        await db.close()

async def _count_users() -> int:
    await _ensure_users_schema()
    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) AS cnt FROM users")
        return int((await cur.fetchone())["cnt"])
    finally:
        await db.close()

async def _fetch_users(page: int, page_size: int = PAGE_SIZE) -> List[Dict]:
    await _ensure_users_schema()
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT tg_id, username, full_name, COALESCE(active,1) AS active, COALESCE(karma,0) AS karma
            FROM users
            ORDER BY (username IS NULL), LOWER(username) ASC, tg_id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, page * page_size),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()

async def _ensure_user_by_username(username: str) -> None:
    """Активируем/создаём запись по username (tg_id может быть NULL)."""
    await _ensure_users_schema()
    db = await get_db()
    try:
        cur = await db.execute("SELECT username FROM users WHERE LOWER(username)=LOWER(?)", (username,))
        row = await cur.fetchone()
        if row:
            await db.execute("UPDATE users SET active=1 WHERE LOWER(username)=LOWER(?)", (username,))
        else:
            await db.execute(
                "INSERT INTO users (tg_id, username, full_name, active) VALUES (NULL, ?, NULL, 1)",
                (username,),
            )
        await db.commit()
    finally:
        await db.close()

async def _set_active_by_username(username: str, active: int) -> int:
    """
    Soft-delete/restore по username. Возвращает кол-во затронутых строк.
    Работает и для записей, где username сохранён с '@', и без '@'.
    """
    await _ensure_users_schema()
    db = await get_db()
    try:
        cur = await db.execute(
            """
            UPDATE users
               SET active = ?
             WHERE LOWER(username) = LOWER(?)
                OR LOWER(username) = LOWER('@' || ?)
            """,
            (active, username, username),
        )
        await db.commit()
        return cur.rowcount or 0
    finally:
        await db.close()

async def _set_active_by_tgid(tg_id: int, active: int) -> None:
    """Быстрые кнопки рядом с юзером (если tg_id есть)."""
    await _ensure_users_schema()
    db = await get_db()
    try:
        await db.execute("UPDATE users SET active=? WHERE tg_id=?", (active, tg_id))
        await db.commit()
    finally:
        await db.close()

# ───────────────── UI ───────────────────────────
def _people_kb(page: int, total: int, users: List[Dict]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()

    for u in users:
        is_active = int(u.get("active", 1)) == 1
        tag = "🟢" if is_active else "⚪️"
        name = u.get("full_name") or (f"@{u['username']}" if u.get("username") else (f"id{u['tg_id']}" if u.get("tg_id") else "—"))
        kb.button(text=f"{tag} {name} • ⚖️{int(u.get('karma',0))}", callback_data=f"admin:people:noop:{u.get('tg_id') or 0}")

        if u.get("tg_id"):
            if is_active:
                kb.button(text="🗑", callback_data=f"admin:people:del:{int(u['tg_id'])}")
            else:
                kb.button(text="♻️", callback_data=f"admin:people:restore:{int(u['tg_id'])}")
        else:
            kb.button(text="ℹ️", callback_data="admin:people:hint_username")

    kb.adjust(2)

    # верхние действия — строго по username
    kb.button(text="➕ Добавить по @username", callback_data="admin:people:add_username")
    kb.button(text="🗑 Удалить по @username", callback_data="admin:people:del_username")

    # пагинация
    has_prev = page > 0
    has_next = (page + 1) * PAGE_SIZE < total
    if has_prev:
        kb.button(text="⬅️", callback_data=f"admin:people:page:{page-1}")
    if has_next:
        kb.button(text="➡️", callback_data=f"admin:people:page:{page+1}")

    kb.button(text="⬅️ Назад", callback_data="admin:panel")
    kb.adjust(2, 3)
    return kb

async def _render_people(e: Message | CallbackQuery, page: int = 0):
    total = await _count_users()
    users = await _fetch_users(page=page, page_size=PAGE_SIZE)
    txt = (
        f"👥 <b>Участники</b>\nВсего: {total}. Стр.: {page+1}\n\n"
        f"• Управление по id оставлено только на быстрых кнопках (если у пользователя есть tg_id).\n"
        f"• Основной режим теперь по <b>@username</b> — кнопки ниже."
    )
    kb = _people_kb(page, total, users).as_markup()

    if isinstance(e, Message):
        await e.answer(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        try:
            await e.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        except TelegramBadRequest:
            with contextlib.suppress(TelegramBadRequest):
                await e.message.edit_reply_markup(reply_markup=kb)
        finally:
            with contextlib.suppress(Exception):
                await e.answer()

# ───────────── entry ─────────────
@router.callback_query(F.data == "admin:people")
async def admin_people_entry(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        return await c.answer("Только для админа.", show_alert=True)
    await _render_people(c, page=0)

@router.callback_query(F.data.startswith("admin:people:page:"))
async def admin_people_page(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        return await c.answer("Нет прав", show_alert=True)
    page = int(c.data.split(":")[-1])
    await _render_people(c, page=page)

@router.callback_query(F.data == "admin:people:hint_username")
async def admin_people_hint_username(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        return await c.answer("Нет прав", show_alert=True)
    await c.answer("У записи нет tg_id — пользуйся действиями по @username ниже.", show_alert=True)

# ───── быстрые кнопки по tg_id (совместимость) ─────
@router.callback_query(F.data.startswith("admin:people:del:"))
async def admin_people_del_by_id(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        return await c.answer("Нет прав", show_alert=True)
    tg_id = int(c.data.split(":")[-1])
    await _set_active_by_tgid(tg_id, 0)
    await c.answer("Скрыт по tg_id (active=0).")
    await _render_people(c, page=0)

@router.callback_query(F.data.startswith("admin:people:restore:"))
async def admin_people_restore_by_id(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        return await c.answer("Нет прав", show_alert=True)
    tg_id = int(c.data.split(":")[-1])
    await _set_active_by_tgid(tg_id, 1)
    await c.answer("Восстановлен по tg_id (active=1).")
    await _render_people(c, page=0)

# ───── режимы ПО @username ─────
async def _enter_add_username_mode(user_id: int):
    # сбрасываем любые старые «жду айди»
    await update_state(user_id, {
        "admin_wait_user_id": False,
        "admin_wait_add_username": True,
        "admin_wait_del_username": False,
    })

async def _enter_del_username_mode(user_id: int):
    await update_state(user_id, {
        "admin_wait_user_id": False,
        "admin_wait_add_username": False,
        "admin_wait_del_username": True,
    })

@router.callback_query(F.data == "admin:people:add_username")
async def admin_people_add_username(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        return await c.answer("Нет прав", show_alert=True)
    await _enter_add_username_mode(c.from_user.id)
    await c.message.answer("Введи <b>@username</b> для добавления/активации.\nНапр.: <code>@og_user</code>", parse_mode=ParseMode.HTML)
    with contextlib.suppress(Exception):
        await c.answer()

@router.callback_query(F.data == "admin:people:del_username")
async def admin_people_del_username(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        return await c.answer("Нет прав", show_alert=True)
    await _enter_del_username_mode(c.from_user.id)
    await c.message.answer("Кого скрыть? Дай <b>@username</b> (soft-delete = active=0).", parse_mode=ParseMode.HTML)
    with contextlib.suppress(Exception):
        await c.answer()

# — перехватываем ЦИФРЫ в режимах username, чтобы NИКОГДА не просило tg_id —
@router.message(F.text.regexp(r"^\d{3,}$"))
async def guard_digits_in_username_mode(m: Message):
    st = await get_state(m.from_user.id)
    if st.get("admin_wait_add_username") or st.get("admin_wait_del_username"):
        return await m.reply("Работаем по <b>@username</b>. Введи @имя, а не числовой ID.", parse_mode=ParseMode.HTML)

# — основной приём текстов в режимах username —
@router.message(F.text)
async def admin_people_text_username(m: Message):
    st = await get_state(m.from_user.id)
    want_add = bool(st.get("admin_wait_add_username"))
    want_del = bool(st.get("admin_wait_del_username"))
    if not (want_add or want_del):
        return

    if not await is_admin_fn(m.from_user.id):
        return await m.reply("Нет прав.")

    uname = _norm_username(m.text or "")
    if not uname:
        return await m.reply("Дай корректный <b>@username</b> (латиница/цифры/нижнее подчёркивание, 3..32).", parse_mode=ParseMode.HTML)

    if want_add:
        await _ensure_user_by_username(uname)
        await pop_state_key(m.from_user.id, "admin_wait_add_username", None)
        await m.reply(f"Готово. <b>@{uname}</b> добавлен/активирован.", parse_mode=ParseMode.HTML)
        return await _render_people(m, page=0)

    if want_del:
        changed = await _set_active_by_username(uname, 0)
        await pop_state_key(m.from_user.id, "admin_wait_del_username", None)
        if changed:
            await m.reply(f"Скрыт: <b>@{uname}</b> (active=0).", parse_mode=ParseMode.HTML)
        else:
            await m.reply(f"Не нашёл пользователя <b>@{uname}</b>.", parse_mode=ParseMode.HTML)
        return await _render_people(m, page=0)
