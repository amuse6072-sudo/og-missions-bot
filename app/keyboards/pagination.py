from __future__ import annotations
import json
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.callbacks import PagerCb


def pagination_kb(page: int, total_pages: int, scope: str, payload: dict | None = None) -> InlineKeyboardMarkup:
    """
    Универсальная пагинация.
    scope — строковый идентификатор списка (например, "missions" / "users")
    payload — произвольный контекст (фильтр/поиск), сериализуем в json
    """
    payload_str = json.dumps(payload, ensure_ascii=False) if payload else None
    prev_page = max(1, page - 1)
    next_page = min(total_pages, page + 1)

    kb = InlineKeyboardBuilder()
    kb.button(
        text="« Пред",
        callback_data=PagerCb(page=prev_page, total=total_pages, scope=scope, payload=payload_str)
    )
    kb.button(
        text=f"{page}/{total_pages}",
        callback_data=PagerCb(page=page, total=total_pages, scope=scope, payload=payload_str)
    )
    kb.button(
        text="След »",
        callback_data=PagerCb(page=next_page, total=total_pages, scope=scope, payload=payload_str)
    )
    kb.adjust(3)
    return kb.as_markup()
