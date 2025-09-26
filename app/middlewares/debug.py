# app/middlewares/debug.py
from __future__ import annotations
from typing import Any, Dict
from loguru import logger
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

# безопасный импорт: если нет state/assistant — не падаем
try:
    from app.services.state import get_state
except Exception:
    async def get_state(_uid: int) -> Dict[str, Any]:
        return {}

try:
    from app.services.ai_assistant import last_error as ai_last_error  # опционально
except Exception:
    ai_last_error = None

class DebugMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            if isinstance(event, Message):
                uid = getattr(event.from_user, "id", 0) or 0
                st = await get_state(uid) if uid else {}
                logger.debug(
                    f"[DBG:MSG] from={uid} text={(event.text or event.caption or '')[:120]!r} "
                    f"flags={{await_ai_text:{st.get('await_ai_text')}, await_text_task:{st.get('await_text_task')}}}"
                )
            elif isinstance(event, CallbackQuery):
                uid = getattr(event.from_user, "id", 0) or 0
                logger.debug(f"[DBG:CB]  from={uid} data={event.data!r}")
        except Exception:
            logger.opt(exception=True).warning("[DBG] pre-handler")

        try:
            result = await handler(event, data)
        except TelegramBadRequest as e:
            # Не роняем поток на «query is too old…» и прочем UI-шуме
            logger.warning(f"[DBG] TelegramBadRequest suppressed: {e}")
            if ai_last_error:
                logger.error(f"[AI last error] {ai_last_error}")
            return None
        except Exception as e:
            logger.opt(exception=True).error(f"[DBG] Handler error: {e}")
            if ai_last_error:
                logger.error(f"[AI last error] {ai_last_error}")
            # Не пробрасываем дальше, чтобы не валить поллинг
            return None
        else:
            if isinstance(event, Message):
                logger.debug("[DBG:MSG] handled OK")
            elif isinstance(event, CallbackQuery):
                logger.debug("[DBG:CB] handled OK")
            return result
