# app/keyboards/__init__.py
from __future__ import annotations
from typing import List, Dict
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ───────────────── Reply-клавиатура (нижнее меню) ──────────────────────────────
def reply_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🎯 Мои миссии"), KeyboardButton(text="🗂 Все миссии")],
        [KeyboardButton(text="➕ Дать миссию"), KeyboardButton(text="🏁 Таблица кармы")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

# ───────────────── Inline-меню (верхние кнопки в сообщениях) ───────────────────
def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎯 Мои миссии", callback_data="menu:mine")
    b.button(text="🗂 Все миссии", callback_data="menu:all")
    b.button(text="➕ Дать миссию", callback_data="menu:add")
    b.button(text="🏁 Таблица кармы", callback_data="menu:lb")
    if is_admin:
        b.button(text="👑 Админ-панель", callback_data="admin:panel")
        b.adjust(2, 2, 1)
    else:
        b.button(text="🏠 Домой", callback_data="menu:home")
        b.adjust(2, 2, 1)
    return b.as_markup()

# ───────────────── Кнопки действий по миссии ───────────────────────────────────
def mission_actions(mid: int, is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Выполнено", callback_data=f"m:{mid}:done")
    b.button(text="📎 Отчёт", callback_data=f"m:{mid}:report")
    b.button(text="⏳ Перенести", callback_data=f"m:{mid}:postmenu")
    b.button(text="❌ Отменить", callback_data=f"m:{mid}:cancel")
    if is_admin:
        b.button(text="🗑 Удалить без штрафа", callback_data=f"m:{mid}:delete_nopenalty")
        b.adjust(2, 2, 1)
    else:
        b.adjust(2, 2)
    return b.as_markup()

# ───────────────── Подменю переноса 1/2/3 дня ─────────────────────────────────
def postpone_menu_kb(mid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ 1 день (0)", callback_data=f"m:{mid}:post:1")
    b.button(text="➕ 2 дня (−1)", callback_data=f"m:{mid}:post:2")
    b.button(text="➕ 3 дня (−2)", callback_data=f"m:{mid}:post:3")
    b.button(text="↩️ Отмена", callback_data=f"m:{mid}:post:cancel")
    b.adjust(3, 1)
    return b.as_markup()

# ───────────────── Быстрое меню для «Мои миссии» ──────────────────────────────
def my_mission_kb(mid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Выполнил", callback_data=f"m:{mid}:done")
    b.button(text="⏳ Перенести", callback_data=f"m:{mid}:postmenu")
    b.adjust(2)
    return b.as_markup()

# ───────────────── Подтверждение назначения ───────────────────────────────────
def confirm_assign_kb(mid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять", callback_data=f"assign:accept:{mid}")
    b.button(text="🚫 Отказаться", callback_data=f"assign:decline:{mid}")
    b.adjust(2)
    return b.as_markup()

# ───────────────── Пагинация ──────────────────────────────────────────────────
def pagination(prefix: str, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_prev:
        b.button(text="⬅️ Назад", callback_data=f"{prefix}:page:{page-1}")
    b.button(text=f"Стр. {page+1}", callback_data="noop")
    if has_next:
        b.button(text="Вперёд ➡️", callback_data=f"{prefix}:page:{page+1}")
    b.adjust(3)
    return b.as_markup()

# ───────────────── Меню добавления миссии (старт) ─────────────────────────────
def add_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👤 Выбрать исполнителя", callback_data="add:pick")
    b.adjust(1)
    return b.as_markup()

# ───────────────── Пикер пользователей (с кармой и активными) ─────────────────
def build_user_picker_kb(users: List[Dict], page: int, total: int, page_size: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in users:
        base = (u.get("full_name") or "").strip() or (f"@{u['username']}" if u.get("username") else f"id{u['tg_id']}")
        karma = u.get("karma", None)
        active = u.get("active_count", None)
        label = f"{base} • ⚖️ {int(karma or 0)} • 🔥 {int(active or 0)}" if karma is not None and active is not None else base
        b.button(text=label, callback_data=f"pick:set:{u['tg_id']}")
    pages = (total + page_size - 1) // page_size if page_size > 0 else 1
    if pages <= 1:
        b.adjust(2, 2, 2, 2)
        return b.as_markup()
    has_prev = page > 0
    has_next = page + 1 < pages
    if has_prev:
        b.button(text="⬅️ Назад", callback_data=f"pick:page:{page-1}")
    b.button(text=f"Стр. {page+1}/{pages}", callback_data="noop")
    if has_next:
        b.button(text="Вперёд ➡️", callback_data=f"pick:page:{page+1}")
    b.adjust(2, 2, 2, 2, 3)
    return b.as_markup()

# ───────────────── Клавиатура ревью отчётов (для админа) ──────────────────────
def review_kb(mid: int, uid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять отчёт", callback_data=f"review:approve:{mid}:{uid}")
    b.button(text="✏️ Отклонить",    callback_data=f"review:reject:{mid}:{uid}")
    b.adjust(2)
    return b.as_markup()
