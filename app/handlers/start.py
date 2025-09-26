from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.enums import ChatType

from app.handlers.ui import send_main_menu
from app.services.missions_service import ensure_user, is_admin

router = Router()

def build_admin_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="👑 Админ-панель")]],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=True,
        input_field_placeholder="Открыть админ-панель",
    )

@router.message(F.text == "/start")
async def start_cmd(m: Message):
    await ensure_user(m.from_user)
    admin = await is_admin(m.from_user.id)

    if m.chat.type == ChatType.PRIVATE and admin:
        await m.answer("👋 Привет! Снизу — кнопка «Админ-панель».", reply_markup=build_admin_reply_kb())
        await send_main_menu(m.bot, m.chat.id, m.from_user.id, reply_to=None)
        return

    # для остальных — просто показываем главное меню и убираем старые reply-кнопки
    await m.answer("🏠 Главное меню", reply_markup=ReplyKeyboardRemove())
    await send_main_menu(m.bot, m.chat.id, m.from_user.id, reply_to=None)
