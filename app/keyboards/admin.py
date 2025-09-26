from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.callbacks import AdminCb
from app.constants import ADMIN_BTNS


def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # 👥 Управление участниками — явный вход в admin:people
    kb.button(text="👥 Участники", callback_data="admin:people")

    # Остальные пункты админки (оставил, как у тебя)
    kb.button(text=ADMIN_BTNS["stats"], callback_data=AdminCb(action="stats"))
    kb.button(text=ADMIN_BTNS["broadcast"], callback_data=AdminCb(action="broadcast"))
    kb.button(text=ADMIN_BTNS["wipe"], callback_data=AdminCb(action="wipe"))
    kb.button(text=ADMIN_BTNS["back"], callback_data=AdminCb(action="back"))

    # Разводка по рядам: 1 ряд — люди, дальше как было
    kb.adjust(1, 2, 1, 1)
    return kb.as_markup()
