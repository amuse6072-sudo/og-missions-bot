from __future__ import annotations
from typing import Callable, Any, Awaitable, Dict, List
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram import BaseMiddleware
from loguru import logger

from app.config import settings
from app.services.missions_service import ensure_user

def _is_allowed(user_id: int, username: str | None) -> bool:
    ids: List[int] = settings.ALLOWED_USER_IDS
    names: List[str] = settings.ALLOWED_USERNAMES
    if not ids and not names:
        return True  # нет белого списка — пускаем всех
    if user_id in ids:
        return True
    if username and ("@" + username) in names:
        return True
    return False

class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            await ensure_user(user)
            if not _is_allowed(user.id, user.username):
                # тихо игнорируем, чтобы не спамить в общий чат
                logger.info(f"[ACCESS] denied for {user.id} @{user.username}")
                return

        return await handler(event, data)
