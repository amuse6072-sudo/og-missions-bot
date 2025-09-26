from __future__ import annotations
from typing import Union

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery


class GroupOnly(BaseFilter):
    """
    Разрешает использование только в группах/супергруппах.
    """
    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        if isinstance(event, Message):
            chat = event.chat
        else:
            chat = event.message.chat if event.message else None
        if not chat:
            return False
        return chat.type in {"group", "supergroup"}
