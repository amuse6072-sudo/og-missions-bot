from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.callbacks import StepperCb


def stepper_kb(step: int, total_steps: int, sid: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if step > 1:
        kb.button(text="⬅️ Назад", callback_data=StepperCb(action="prev", sid=sid, step=step))
    if step < total_steps:
        kb.button(text="➡️ Далее", callback_data=StepperCb(action="next", sid=sid, step=step))
    else:
        kb.button(text="💾 Сохранить", callback_data=StepperCb(action="save", sid=sid, step=step))
    kb.button(text="✖️ Отмена", callback_data=StepperCb(action="cancel", sid=sid, step=step))
    kb.adjust(2, 2)
    return kb.as_markup()
