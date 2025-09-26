# app/services/notifications.py
from __future__ import annotations
from typing import Optional, Sequence
from aiogram.enums import ParseMode
from loguru import logger

from app.services.assistant_tone import (
    MissionBrief,
    line_created,
    line_sent_to_assignee,
    line_assignee_prompt,
    line_accepted,
    line_declined,
    line_postponed,
)

async def _safe_dm(bot, user_id: int, text: str, reply_markup=None, html: bool = True) -> bool:
    try:
        await bot.send_message(user_id, text, parse_mode=ParseMode.HTML if html else None, reply_markup=reply_markup)
        return True
    except Exception as e:
        logger.debug(f"[DM fail] {user_id}: {e}")
        return False

async def _safe_chat(bot, chat_id: int, text: str, reply_markup=None, html: bool = True) -> bool:
    try:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML if html else None, reply_markup=reply_markup)
        return True
    except Exception as e:
        logger.debug(f"[CHAT fail] {chat_id}: {e}")
        return False

# ── создание / назначение ─────────────────────────────────────────────────────

async def notify_created(
    bot,
    *,
    mid: int,
    group_chat_id: Optional[int],
    author_id: int,
    assignee_id: int,
    brief: MissionBrief,
    post_keyboard=None,
    assignee_keyboard=None,
    author_username: Optional[str] = None,
):
    # заказчику — сленговый фидбек
    await _safe_dm(bot, author_id, line_created(brief))

    # в групповой чат — «ушла на рассмотрение»
    if group_chat_id:
        await _safe_chat(
            bot,
            group_chat_id,
            f"📌 #{mid} {line_sent_to_assignee(brief)}",
            reply_markup=post_keyboard,
        )

    # исполнителю — личка с кнопками принять/отказаться
    ok = await _safe_dm(bot, assignee_id, line_assignee_prompt(brief), reply_markup=assignee_keyboard)
    if not ok and group_chat_id:
        # просим исполнителя открыть бота
        await _safe_chat(
            bot,
            group_chat_id,
            f"⚠️ <a href='tg://user?id={assignee_id}'>Исполнитель</a>, открой бота в личке, чтобы получать задачи.",
        )

# ── ответы исполнителя ────────────────────────────────────────────────────────

async def notify_accept(bot, *, mid: int, group_chat_id: Optional[int], author_id: int, assignee_id: int, assignee_display: str):
    text = f"#{mid} " + line_accepted(assignee_display)
    if group_chat_id:
        await _safe_chat(bot, group_chat_id, text)
    await _safe_dm(bot, author_id, text)

async def notify_decline(bot, *, mid: int, group_chat_id: Optional[int], author_id: int, assignee_id: int, assignee_display: str, penalty: int):
    text = f"#{mid} " + line_declined(assignee_display, penalty)
    if group_chat_id:
        await _safe_chat(bot, group_chat_id, text)
    await _safe_dm(bot, author_id, text)

async def notify_postpone(bot, *, mid: int, group_chat_id: Optional[int], author_id: int, assignee_id: int, assignee_display: str, days: int, penalty: int, deadline_str: str):
    text = f"#{mid} {line_postponed(assignee_display, days, penalty)} → новый дедлайн: {deadline_str}"
    if group_chat_id:
        await _safe_chat(bot, group_chat_id, text)
    await _safe_dm(bot, author_id, text)
