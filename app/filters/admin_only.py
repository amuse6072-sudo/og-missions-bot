from __future__ import annotations

import os
from typing import Optional, Union

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

try:
    # предпочтительно: из settings
    from app.config import settings  # type: ignore
except Exception:
    settings = None  # type: ignore


class AdminOnly(BaseFilter):
    """
    Пускает только админа (по tg_id).
    Источник: settings.ADMIN_USER_ID или переменная окружения ADMIN_USER_ID.
    """

    def __init__(self, admin_id: Optional[int] = None) -> None:
        cfg_id = None
        try:
            cfg_id = getattr(settings, "ADMIN_USER_ID", None) if settings else None
        except Exception:
            cfg_id = None
        env_id = int(os.getenv("ADMIN_USER_ID")) if os.getenv("ADMIN_USER_ID") else None
        self.admin_id = admin_id or cfg_id or env_id

    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        if self.admin_id is None:
            return False
        user = getattr(event, "from_user", None)
        uid = getattr(user, "id", None)
        return uid == self.admin_id
