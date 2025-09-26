from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.callbacks import MissionCb
from app.constants import MISSION_BTNS


def mission_actions(mission_id: int, role: str = "user", status: str = "open", page: int | None = None) -> InlineKeyboardMarkup:
    """
    role: "user" | "admin"
    status: "open" | "in_progress" | "done" | "failed"
    """
    kb = InlineKeyboardBuilder()

    if status == "open":
        kb.button(text=MISSION_BTNS["accept"], callback_data=MissionCb(action="accept", mid=mission_id, page=page))
    else:
        kb.button(text=MISSION_BTNS["details"], callback_data=MissionCb(action="details", mid=mission_id, page=page))

    if status in {"in_progress"}:
        kb.button(text=MISSION_BTNS["done"], callback_data=MissionCb(action="done", mid=mission_id, page=page))
        kb.button(text=MISSION_BTNS["fail"], callback_data=MissionCb(action="fail", mid=mission_id, page=page))

    if role == "admin":
        kb.button(text=MISSION_BTNS["assign"], callback_data=MissionCb(action="assign", mid=mission_id, page=page))
        kb.button(text=MISSION_BTNS["edit"], callback_data=MissionCb(action="edit", mid=mission_id, page=page))
        kb.button(text=MISSION_BTNS["delete"], callback_data=MissionCb(action="delete", mid=mission_id, page=page))

    kb.button(text=MISSION_BTNS["back"], callback_data=MissionCb(action="back", mid=mission_id, page=page))

    # Компоновка: первая строка 2, затем по 3 в ряд, затем Назад
    kb.adjust(2, 3, 1)
    return kb.as_markup()
