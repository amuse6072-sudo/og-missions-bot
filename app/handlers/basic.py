# app/handlers/basic.py
from __future__ import annotations

import os
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from loguru import logger

from app.db import get_db
from app.services.missions_service import (
    ensure_user,
    find_user_by_username,
    create_mission,
    mission_summary,
    set_status,
)
from app.services.ai_assistant import classify
from app.keyboards import (
    mission_actions,
    review_kb,
    confirm_assign_kb,
    postpone_menu_kb,
)
from app.utils.time import parse_iso_or_date, fmt_dt
from app.services.gifs import pick_gif
from app.services.state import update_state, pop_state_key, get_state

try:
    from app.config import settings  # type: ignore
except Exception:
    settings = None  # type: ignore

router = Router()


def _clamp_pts(x: Optional[int]) -> int:
    try:
        v = int(x or 1)
    except Exception:
        v = 1
    return max(1, min(5, v))


async def _active_missions_count(tg_id: int) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM missions m
            JOIN assignments a ON a.mission_id = m.id
            WHERE a.assignee_tg_id = ?
              AND COALESCE(m.status,'') NOT IN ('DONE','CANCELLED','CANCELLED_ADMIN')
            """,
            (tg_id,)
        )
        row = await cur.fetchone()
        return int(row['cnt'] if row and 'cnt' in row.keys() else 0)
    finally:
        await db.close()


async def _display_by_tg(tg_id: int) -> str:
    db = await get_db()
    try:
        cur = await db.execute("SELECT username, full_name FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if row:
            if row["username"]:
                return f"@{row['username']}"
            if row["full_name"]:
                return row["full_name"]
        return f"id{tg_id}"
    finally:
        await db.close()


def _resolve_report_chat_id() -> Optional[int]:
    try:
        gid = getattr(settings, "REPORT_CHAT_ID", None)
    except Exception:
        gid = None
    if gid:
        return gid
    env_gid = os.getenv("REPORT_CHAT_ID")
    if env_gid and env_gid.lstrip("-").isdigit():
        return int(env_gid)
    try:
        admin_id = getattr(settings, "ADMIN_USER_ID", None)
        return admin_id
    except Exception:
        env_admin = os.getenv("ADMIN_USER_ID")
        return int(env_admin) if env_admin and env_admin.isdigit() else None


# /add "описание" @username 2025-09-03T18:00
@router.message(F.text.startswith("/add"))
async def add_quick(m: Message):
    try:
        payload = (m.text or "")[len("/add"):].strip()
        if not payload:
            await m.reply('Формат: /add "описание" @username YYYY-MM-DDTHH:MM')
            return

        title = ""
        username = ""
        deadline_str: Optional[str] = None
        rest = ""

        if payload.startswith('"'):
            end = payload.find('"', 1)
            if end == -1:
                await m.reply('Формат: /add "описание" @username YYYY-MM-DDTHH:MM')
                return
            title = payload[1:end].strip()
            rest = payload[end + 1 :].strip()
        else:
            parts = payload.split(" @", 1)
            if len(parts) == 2:
                title = parts[0].strip()
                rest = "@" + parts[1].strip()
            else:
                await m.reply('Формат: /add "описание" @username YYYY-MM-DDTHH:MM')
                return

        pieces = rest.split()
        if len(pieces) >= 1:
            username = pieces[0]
        if len(pieces) >= 2:
            deadline_str = pieces[1]

        deadline = parse_iso_or_date(deadline_str) if deadline_str else None

        await ensure_user(m.from_user)
        creator_tg = m.from_user.id
        creator_display = f"@{m.from_user.username}" if m.from_user.username else (m.from_user.full_name or f"id{creator_tg}")

        assignee = await find_user_by_username(username)
        if not assignee:
            await m.reply(f"Не нашёл пользователя {username}. Попроси его нажать /start.")
            return
        assignee_tg = int(assignee.get("tg_id"))
        assignee_display = await _display_by_tg(assignee_tg)

        active_cnt = await _active_missions_count(assignee_tg)
        if active_cnt >= 10:
            await m.reply(f"❗️У {assignee_display} уже {active_cnt} активных задач. Лимит — 10.")
            return

        difficulty, _, _ = classify(title, deadline)
        pts = _clamp_pts(difficulty)

        mid = await create_mission(
            title=title,
            description=title,
            author_tg_id=creator_tg,
            assignees=[assignee_tg],
            deadline_ts=deadline,
            difficulty=pts,
            difficulty_label=str(pts),
        )

        dl = fmt_dt(deadline, "%d.%m %H:%M") if deadline else "—"
        await m.bot.send_message(
            assignee_tg,
            f"🆕 Тебе назначена миссия #{mid}:\n«{title}»\n⏰ {dl}\n\nПодтверди участие.",
            reply_markup=confirm_assign_kb(mid),
        )

        try:
            await m.bot.send_message(
                creator_tg,
                f"📨 Отправил {assignee_display} запрос на подтверждение по миссии #{mid}.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        await m.answer("Ок, запрос на подтверждение отправлен ✅")
        gif_id = await pick_gif("task_create")
        if gif_id:
            await m.answer_animation(gif_id)

    except Exception as e:
        logger.exception(e)
        await m.reply("Не удалось создать миссию. Проверь формат.")


# Совместимость по колбэкам «м:{mid}:{action}»
@router.callback_query(F.data.startswith("m:"))
async def mission_action(c: CallbackQuery):
    try:
        _, sid, action = c.data.split(":")
        mid = int(sid)

        if action in ("report", "done"):
            await update_state(c.from_user.id, {"report_mid": mid})
            await c.message.answer(
                "📎 Пришли фото/видео или текст отчёта одним сообщением.\n"
                "После этого задача уйдёт админу на проверку."
            )
            await set_status(mid, "REVIEW")
            await c.answer("Жду отчёт.")

        elif action == "progress":
            await set_status(mid, "IN_PROGRESS")
            await c.answer("Отметил как «ещё выполняю».", show_alert=False)

        elif action == "postpone":
            await c.message.edit_reply_markup(reply_markup=postpone_menu_kb(mid))
            await c.answer("Выбери, на сколько дней перенести.")

        elif action == "cancel":
            await c.answer("Отмена через UI скоро. Пока удали и создай заново.", show_alert=True)

    except Exception as e:
        logger.exception(e)
        await c.answer("Ошибка действия", show_alert=True)


# Приём отчёта и пересылка админу (УЗКИЙ ФИЛЬТР — ТОЛЬКО МЕДИА/ДОКУМЕНТ)
@router.message(F.photo | F.video | F.document)
async def receive_report_message(m: Message):
    st = await get_state(m.from_user.id)
    mid = st.get("report_mid")
    if not mid:
        return
    try:
        # Текст к отчёту тоже прилетит как caption → попадёт сюда
        s = await mission_summary(int(mid))
        title = (s.get("mission") or {}).get("title") if s else f"#{mid}"

        admin_chat = _resolve_report_chat_id()
        author_display = f"@{m.from_user.username}" if m.from_user.username else (m.from_user.full_name or f"id{m.from_user.id}")
        caption = (
            f"🧾 Отчёт по задаче #{mid} «{title}»\n"
            f"От: {author_display}"
        )
        kb = review_kb(int(mid), m.from_user.id)

        if m.photo:
            await m.bot.send_photo(admin_chat or m.from_user.id, m.photo[-1].file_id, caption=caption, reply_markup=kb)
        elif m.video:
            await m.bot.send_video(admin_chat or m.from_user.id, m.video.file_id, caption=caption, reply_markup=kb)
        elif m.document:
            await m.bot.send_document(admin_chat or m.from_user.id, m.document.file_id, caption=caption, reply_markup=kb)

        try:
            await set_status(int(mid), "REVIEW")
        except Exception:
            pass

        await m.reply("✅ Отправил отчёт админу. Ждём проверку.")
    finally:
        await pop_state_key(m.from_user.id, "report_mid", None)
