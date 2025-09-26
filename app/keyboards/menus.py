from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.callbacks import MenuCb
from app.constants import MAIN_MENU


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=MAIN_MENU["missions"], callback_data=MenuCb(action="missions"))
    kb.button(text=MAIN_MENU["my"], callback_data=MenuCb(action="my"))
    kb.button(text=MAIN_MENU["stats"], callback_data=MenuCb(action="stats"))
    kb.button(text=MAIN_MENU["help"], callback_data=MenuCb(action="help"))
    if is_admin:
        kb.button(text=MAIN_MENU["admin"], callback_data=MenuCb(action="admin"))
    kb.adjust(2, 2, 1 if is_admin else 0)
    return kb.as_markup()
