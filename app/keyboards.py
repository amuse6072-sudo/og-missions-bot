from __future__ import annotations
from typing import List, Dict, Optional

from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup


# ───────────────── Главное меню ─────────────────

def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Нижняя reply-клава: все базовые действия на кнопках.
    """
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Дать миссию")
    kb.button(text="🎯 Мои миссии")
    kb.button(text="🗂 Все миссии")
    kb.button(text="🏁 Таблица кармы")
    if is_admin:
        kb.button(text="👑 Админ-панель")
    # 2 ряда по 2, затем последняя одиночная
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=False)


# ──────────────── Выбор исполнителя ─────────────

def build_user_picker_kb(
    users: List[Dict],
    page: int,
    total: int,
    page_size: int,
    with_cancel: bool = True,
) -> InlineKeyboardMarkup:
    """
    users: [{tg_id, username, full_name, karma?, active_count?, active?}, ...]
    Коллбеки совместимы с текущими хендлерами:
      - pick:set:<tg_id>
      - pick:page:<num>
      - add:cancel (новая, опциональная — можно игнорить в хендлере)
    """
    kb = InlineKeyboardBuilder()

    # одна строка = [имя • карма • актив]  (тач по строке выбирает исполнителя)
    for u in users:
        name = u.get("full_name") or (f"@{u['username']}" if u.get("username") else f"id{u['tg_id']}")
        karma = int(u.get("karma") or 0)
        active = int(u.get("active_count") or 0)
        label = f"{name} • ⚖️{karma} • 🔥{active}"
        kb.button(text=label, callback_data=f"pick:set:{int(u['tg_id'])}")

    # пагинация
    has_prev = page > 0
    has_next = (page + 1) * page_size < total
    if has_prev:
        kb.button(text="⬅️", callback_data=f"pick:page:{page-1}")
    if has_next:
        kb.button(text="➡️", callback_data=f"pick:page:{page+1}")

    # отмена выбора (опционально, не ломает текущую логику)
    if with_cancel:
        kb.button(text="✖️ Отмена", callback_data="add:cancel")

    # люди по одному в ряд, затем стрелки/отмена в один ряд
    if has_prev or has_next or with_cancel:
        kb.adjust(1, 3)
    else:
        kb.adjust(1)

    return kb.as_markup()


# ───────────────── Мои миссии ──────────────────

def my_mission_kb(mid: int) -> InlineKeyboardMarkup:
    """
    Карточка назначения миссии для исполнителя.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"assign:accept:{mid}")
    kb.button(text="❌ Отказаться", callback_data=f"assign:decline:{mid}")
    kb.button(text="⏳ Перенести", callback_data=f"m:{mid}:postmenu")
    kb.adjust(2, 1)
    return kb.as_markup()


# ──────────────── Действия по миссии ────────────

def mission_actions(mid: int) -> InlineKeyboardMarkup:
    """
    Общие действия по миссии. Удаление без штрафа проверяется на права в хендлере.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="⏳ Перенести", callback_data=f"m:{mid}:postmenu")
    kb.button(text="🗑 Удалить без штрафа (админ)", callback_data=f"m:{mid}:delete_nopenalty")
    kb.adjust(1, 1)
    return kb.as_markup()


def postpone_menu_kb(mid: int) -> InlineKeyboardMarkup:
    """
    Подменю переноса дедлайна (штрафы/без штрафа).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ 1 день (без штрафа)", callback_data=f"m:{mid}:post:1")
    kb.button(text="➕ 2 дня (−1 карма)", callback_data=f"m:{mid}:post:2")
    kb.button(text="➕ 3 дня (−1 карма)", callback_data=f"m:{mid}:post:3")
    kb.button(text="⬅️ Назад", callback_data=f"m:{mid}:post:cancel")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def review_kb(mid: int) -> InlineKeyboardMarkup:
    """
    Ревью отчёта: принять / отправить на доработку.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять отчёт", callback_data=f"m:{mid}:review:ok")
    kb.button(text="🛠 На доработку", callback_data=f"m:{mid}:review:rework")
    kb.adjust(2)
    return kb.as_markup()


def add_menu_kb() -> InlineKeyboardMarkup:
    """
    Первичная точка создания миссии (без AI-флоу).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Выбрать исполнителя", callback_data="add:pick")
    kb.adjust(1)
    return kb.as_markup()


# ──────────────── Пагинация «Все миссии» ───────

def pagination(prefix: str, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    """
    Универсальная пагинация для списков миссий.
    prefix: префикс коллбэка (например, 'all' или 'mine')
    """
    kb = InlineKeyboardBuilder()
    if has_prev:
        kb.button(text="⬅️", callback_data=f"{prefix}:page:{page-1}")
    if has_next:
        kb.button(text="➡️", callback_data=f"{prefix}:page:{page+1}")
    if has_prev or has_next:
        kb.adjust(2)
    return kb.as_markup()


# ──────────────── Кнопки принятия задания ──────

def confirm_assign_kb(mid: int) -> InlineKeyboardMarkup:
    """
    Дублирующая пара «Принять / Отказаться» — для подтверждений.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"assign:accept:{mid}")
    kb.button(text="❌ Отказаться", callback_data=f"assign:decline:{mid}")
    kb.adjust(2)
    return kb.as_markup()
