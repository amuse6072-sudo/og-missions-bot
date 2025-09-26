# app/handlers/text_flow.py
from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from loguru import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import os

router = Router(name="text_flow")

REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "0") or "0")
TZ = os.getenv("TZ", os.getenv("TIMEZONE", "Europe/Kyiv"))
ZONE = ZoneInfo(TZ)

@router.message(F.text & ~F.text.startswith("/"))
async def on_free_text(msg: Message):
    text = (msg.text or "").strip()
    if not text:
        return

    # 1) Ассистент → анализ
    from app.services.ai_assistant import assistant_summarize_quick, render_street_mission
    analysis = await assistant_summarize_quick(text)

    # 2) Нормализуем дедлайн
    due_at = None
    if analysis.get("deadline_ts"):
        due_at = datetime.fromtimestamp(int(analysis["deadline_ts"]), tz=ZONE)

    # 3) Создаём миссию (используем твой сервис; если сигнатура другая — просто скорректируй аргументы)
    created = None
    try:
        from app.services import missions_service
        created = await missions_service.create_mission(
            title=analysis["title"],
            description=analysis["description_og"],    # важнo: исходный текст юзера
            due_at=due_at,
            priority=analysis.get("priority", "normal"),
            created_by=msg.from_user.id,
            assignee_username=analysis.get("assignee_username"),
            difficulty=analysis.get("difficulty_points"),
            karma=analysis.get("karma_points"),
        )
    except Exception as e:
        logger.warning(f"[text_flow] create_mission failed: {e}")

    # 4) Уличный шаблон (предпросмотр пользователю)
    street = render_street_mission(
        analysis,
        requester_name=msg.from_user.full_name,
        assignee_name=analysis.get("assignee_username"),
    )
    await msg.answer(street)

    # 5) Рассылка: исполнителю (если указан) + в общий чат (если задан REPORT_CHAT_ID)
    try:
        from aiogram import Bot
        bot: Bot = msg.bot

        # исполнителю
        if analysis.get("assignee_username"):
            # если у тебя есть map username->tg_id — можно найти id;
            # иначе шлём в общий чат сразу
            pass

        # общий чат (репорт)
        if REPORT_CHAT_ID:
            await bot.send_message(REPORT_CHAT_ID, f"🆕 Новая миссия:\n{street}")

    except Exception as e:
        logger.warning(f"[text_flow] broadcast failed: {e}")
