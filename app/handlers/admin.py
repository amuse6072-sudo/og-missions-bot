from __future__ import annotations
import os
import re
from typing import Optional, List, Dict

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db import get_db
from app.config import settings
from app.services.missions_service import ensure_user, is_admin
from app.services.karma import add_karma_tg
from app.services.ranking import leaderboard_text
from app.services.state import update_state, get_state

router = Router()

# ───────────────── helpers ─────────────────
def _resolve_group_id() -> Optional[int]:
    gid = getattr(settings, "REPORT_CHAT_ID", None) if hasattr(settings, "REPORT_CHAT_ID") else None
    if gid:
        return gid
    env_gid = os.getenv("REPORT_CHAT_ID")
    if env_gid and env_gid.lstrip("-").isdigit():
        return int(env_gid)
    return getattr(settings, "ADMIN_USER_ID", None) if hasattr(settings, "ADMIN_USER_ID") else None

_username_rx = re.compile(r"^@?([A-Za-z0-9_]{3,32})$")

def _norm_username(s: str) -> str | None:
    s = (s or "").strip()
    m = _username_rx.match(s)
    if not m:
        return None
    return m.group(1).lower()

async def _soft_delete_by_username(uname: str) -> int:
    """
    active=0 по username; поддерживает сохранённые в БД значения с '@' и без '@'.
    Возвращает количество затронутых строк.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """
            UPDATE users
               SET active = 0
             WHERE LOWER(username) = LOWER(?)
                OR LOWER(username) = LOWER('@' || ?)
            """,
            (uname, uname),
        )
        await db.commit()
        return cur.rowcount or 0
    finally:
        await db.close()

# ───────────────── Админ-панель ─────────────────
def admin_inline_menu():
    b = InlineKeyboardBuilder()
    b.button(text="🏆 Лидерборд", callback_data="admin:lb")
    b.button(text="🔧 Карма", callback_data="admin:karma")
    b.button(text="👥 Участники", callback_data="admin:people")  # уводим в people-flow
    b.button(text="↩️ Закрыть", callback_data="admin:close")
    b.adjust(2, 2)
    return b.as_markup()

@router.message(F.text.in_({"👑 Админ-панель", "Админ-панель"}))
async def admin_panel_from_reply_exact(m: Message):
    if not await is_admin(m.from_user.id):
        return
    await ensure_user(m.from_user)
    await m.answer("👑 Админ-панель:", reply_markup=admin_inline_menu())

@router.message(F.text == "/admin")
@router.message(F.text.regexp(r"(?i)админ[\s\-]*панел"))
async def admin_panel_from_text(m: Message):
    if not await is_admin(m.from_user.id):
        return
    await ensure_user(m.from_user)
    await m.answer("👑 Админ-панель:", reply_markup=admin_inline_menu())

@router.callback_query(F.data == "admin:panel")
async def admin_root(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer("Только для админа", show_alert=True); return
    await ensure_user(c.from_user)
    await c.message.edit_text("👑 Админ-панель:", reply_markup=admin_inline_menu())
    await c.answer()

@router.callback_query(F.data == "admin:close")
async def admin_close(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    try:
        await c.message.delete()
    except Exception:
        pass
    await c.answer()

# ───────────────── Лидерборд ─────────────────
def _lb_menu_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="📣 В группу", callback_data="admin:lb:post")
    b.button(text="↩️ Назад", callback_data="admin:panel")
    b.adjust(1, 1)
    return b

@router.callback_query(F.data == "admin:lb")
async def admin_lb_open(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    txt = await leaderboard_text(limit=15)
    await c.message.edit_text("🏁 <b>Рейтинг движа</b>\n\n" + txt, parse_mode=ParseMode.HTML, reply_markup=_lb_menu_kb().as_markup())
    await c.answer()

@router.callback_query(F.data == "admin:lb:post")
async def admin_lb_post(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    gid = _resolve_group_id()
    if not gid:
        await c.answer("Не вижу групповой чат (REPORT_CHAT_ID).", show_alert=True); return
    txt = await leaderboard_text(limit=15)
    try:
        await c.bot.send_message(gid, "🏁 <b>Рейтинг движа</b>\n\n" + txt, parse_mode=ParseMode.HTML)
        await c.answer("Закинул рейтинг в группу.")
    except Exception:
        await c.answer("Не смог отправить в группу.", show_alert=True)

# ───────────────── Карма ─────────────────
def _karma_delta_kb(uid: int):
    b = InlineKeyboardBuilder()
    for delta in (-10, -5, -1, +1, +5, +10):
        sign = "➖" if delta < 0 else "➕"
        b.button(text=f"{sign}{abs(delta)}", callback_data=f"admin:karma:set:{uid}:{delta}")
    b.button(text="↩️ Назад", callback_data="admin:karma")
    b.adjust(3, 3, 1)
    return b.as_markup()

async def _top_users(limit: int = 10) -> List[Dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT tg_id, username, full_name, karma FROM users ORDER BY karma DESC LIMIT ?",
            (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()

@router.callback_query(F.data == "admin:karma")
async def admin_karma_root(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    users = await _top_users()
    b = InlineKeyboardBuilder()
    for u in users:
        label = f"@{u['username']}" if u.get("username") else (u.get("full_name") or f"id{u['tg_id']}")
        b.button(text=f"{label} ({u['karma']})", callback_data=f"admin:karma:user:{u['tg_id']}")
    b.button(text="↩️ Назад", callback_data="admin:panel")
    b.adjust(1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    await c.message.edit_text("Выбери участника для корректировки кармы:", reply_markup=b.as_markup())
    await c.answer()

@router.callback_query(F.data.startswith("admin:karma:user:"))
async def admin_karma_user(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    _, _, _, uid_s = c.data.split(":")
    uid = int(uid_s)
    await c.message.edit_text(f"Корректировка кармы для id{uid}:", reply_markup=_karma_delta_kb(uid))
    await c.answer()

@router.callback_query(F.data.startswith("admin:karma:set:"))
async def admin_karma_set(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    try:
        _, _, _, uid_s, delta_s = c.data.split(":")
        uid = int(uid_s)
        delta = int(delta_s)
    except Exception:
        await c.answer("Некорректные данные", show_alert=True); return

    await add_karma_tg(uid, delta, "Ручная корректировка админом")
    await c.answer("Готово")
    await c.message.edit_text(f"Готово. Изменил карму id{uid} на {delta:+d}.", reply_markup=_karma_delta_kb(uid))

# ───────────────── Пользователи (@username) ─────────────────
def _users_menu_kb(users: List[Dict]) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for u in users:
        label = f"@{u['username']}" if u.get("username") else (u.get("full_name") or f"id{u['tg_id']}")
        b.button(text=f"{label} ({u['karma']})", callback_data=f"admin:users:user:{u['tg_id']}")
    b.button(text="➕ Добавить по @username", callback_data="admin:users:add_username")
    b.button(text="🗑 Удалить по @username", callback_data="admin:users:del_username")
    b.button(text="↩️ Назад", callback_data="admin:panel")
    b.adjust(1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3)
    return b

@router.callback_query(F.data == "admin:users")
async def admin_users_root(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    users = await _top_users(limit=15)
    await c.message.edit_text("👥 Участники:", reply_markup=_users_menu_kb(users).as_markup())
    await c.answer()

# — Добавление по username —
@router.callback_query(F.data == "admin:users:add_username")
async def admin_users_add_username(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    await update_state(c.from_user.id, {"add_step": None, "new_user": None, "add_wait_username": True})
    await c.message.answer("Введи <b>@username</b> для добавления/активации.\nНапример: <code>@og_user</code>", parse_mode=ParseMode.HTML)
    await c.answer()

@router.message(F.text & ~F.text.regexp(r"^/"))
async def admin_users_add_username_capture(m: Message):
    st = await get_state(m.from_user.id)
    if not st.get("add_wait_username"):
        return
    if not await is_admin(m.from_user.id):
        await update_state(m.from_user.id, {"add_wait_username": False})
        return

    uname = _norm_username(m.text or "")
    if not uname:
        return await m.reply("Дай корректный <b>@username</b> (латиница/цифры/нижнее подчёркивание, 3..32).", parse_mode=ParseMode.HTML)

    # создаём/активируем пользователя; tg_id может быть неизвестен
    db = await get_db()
    try:
        cur = await db.execute("SELECT username FROM users WHERE LOWER(username)=LOWER(?)", (uname,))
        row = await cur.fetchone()
        if row:
            await db.execute("UPDATE users SET active=1 WHERE LOWER(username)=LOWER(?)", (uname,))
        else:
            await db.execute("INSERT INTO users (tg_id, username, full_name, active) VALUES (NULL, ?, NULL, 1)", (uname,))
        await db.commit()
    finally:
        await db.close()

    await update_state(m.from_user.id, {"add_wait_username": False})
    await m.reply(f"Готово. <b>@{uname}</b> добавлен/активирован.", parse_mode=ParseMode.HTML)

# — Удаление по username —
@router.callback_query(F.data == "admin:users:del_username")
async def admin_users_del_username(c: CallbackQuery):
    if not await is_admin(c.from_user.id):
        await c.answer(); return
    await update_state(c.from_user.id, {"del_user_wait_username": True, "add_wait_username": False, "add_step": None, "new_user": None})
    await c.message.answer("Кого скрыть? Дай <b>@username</b> (soft-delete = active=0).", parse_mode=ParseMode.HTML)
    await c.answer()

@router.message(F.text.regexp(r"^@\w{3,32}$"))
async def admin_users_del_username_capture(m: Message):
    st = await get_state(m.from_user.id)
    if not st.get("del_user_wait_username"):
        return
    if not await is_admin(m.from_user.id):
        await update_state(m.from_user.id, {"del_user_wait_username": False}); return

    uname = _norm_username(m.text or "")
    if not uname:
        return await m.reply("Дай корректный <b>@username</b> (латиница/цифры/нижнее подчёркивание, 3..32).", parse_mode=ParseMode.HTML)

    changed = await _soft_delete_by_username(uname)
    await update_state(m.from_user.id, {"del_user_wait_username": False})

    if changed:
        await m.reply(f"Скрыт: <b>@{uname}</b> (active=0).", parse_mode=ParseMode.HTML)
    else:
        await m.reply(f"Не нашёл пользователя <b>@{uname}</b>.", parse_mode=ParseMode.HTML)
