# app/handlers/missions.py
from __future__ import annotations

import contextlib
import json
from datetime import datetime
from typing import Optional, Dict, List

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dateutil import tz
from loguru import logger

from app.db import get_db
from app.services import karma as karma_svc
from app.services.ai_assistant import assistant_summarize_quick
from app.services.assistant_tone import (  # OG-тон
    line_done,
    line_rework,
)
from app.services.karma_policy import rework_penalty  # штраф за доработку
from app.services.missions_service import (
    add_event,
    create_appeal,
    create_mission,
    ensure_user,
    find_user_by_name_prefix,
    find_user_by_username,
    get_assignees_tg,
    is_admin as is_admin_fn,
    list_users,
    mark_done,
    mission_summary,
    postpone_days,
    set_status,
)

router = Router()
GROUP_ANONYMOUS_ID = 1087968824  # @GroupAnonymousBot

# ───────── helpers ─────────

def _fmt_deadline(ts: Optional[int], tz_name: str = "Europe/Kyiv") -> str:
    if not ts:
        return "не указан"
    zone = tz.gettz(tz_name)
    return datetime.fromtimestamp(ts, tz=zone).strftime("%d.%m %H:%M")

def _mention(tg_id: int, label: Optional[str] = None) -> str:
    name = (label or f"id{tg_id}").replace("<", "").replace(">", "")
    return f"<a href='tg://user?id={tg_id}'>{name}</a>"

async def _notify_assignee(bot, assignee_tg_id: int, card_text: str) -> bool:
    try:
        await bot.send_message(assignee_tg_id, f"🔔 Вам назначена миссия:\n{card_text}", parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        logger.debug(f"[DM notify fail] {assignee_tg_id}: {e}")
        return False

# ───────── локальные клавиатуры ─────────

def _mission_actions_kb(mid: int, is_admin: bool = False):
    b = InlineKeyboardBuilder()
    b.button(text="📎 Отчёт", callback_data=f"m:{mid}:report")
    b.button(text="⏳ Перенести", callback_data=f"m:{mid}:postmenu")
    b.button(text="✅ Готово", callback_data=f"m:{mid}:done")
    if is_admin:
        b.button(text="❌ Отменить", callback_data=f"m:{mid}:cancel")
        b.button(text="👑 Админ-панель", callback_data=f"m:{mid}:admin")
    b.adjust(2, 2, 1 if is_admin else 0)
    return b.as_markup()

def _postpone_menu_kb(mid: int):
    b = InlineKeyboardBuilder()
    b.button(text="＋1 день (0)", callback_data=f"m:{mid}:post:1")
    b.button(text="＋2 дня (−1)", callback_data=f"m:{mid}:post:2")
    b.button(text="＋3 дня (−2)", callback_data=f"m:{mid}:post:3")
    b.button(text="Отмена", callback_data=f"m:{mid}:post:cancel")
    b.adjust(3, 1)
    return b.as_markup()

def _review_kb(mid: int, from_user_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять", callback_data=f"review:approve:{mid}:{from_user_id}")
    b.button(text="🔁 На доработку", callback_data=f"review:reject:{mid}:{from_user_id}")
    b.adjust(2)
    return b.as_markup()

async def _post_report_for_review(bot, mid: int, from_user_id: int, text: str):
    target = _admin_target()
    if not target:
        return
    try:
        await bot.send_message(
            target,
            f"🧾 Отчёт по миссии #{mid}:\n{text}",
            reply_markup=_review_kb(mid, from_user_id),
        )
    except Exception as e:
        logger.warning(f"[REVIEW SEND] {e}")

def _assign_menu_reply_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="✍️ Текстом")
    kb.button(text="👤 Выбрать исполнителя")
    kb.button(text="🙈 Скрыть меню")
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True, selective=True, input_field_placeholder="Опишите задачу…")

def _build_user_picker_simple(users: List[Dict]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    count = 0
    for u in users:
        tg_id = int(u["tg_id"])
        if tg_id == GROUP_ANONYMOUS_ID:
            continue
        label = (u.get("full_name") or "").strip() or (("@" + u.get("username")) if u.get("username") else f"id{tg_id}")
        kb.button(text=label, callback_data=f"pick:set:{tg_id}")
        count += 1
    if count == 0:
        kb.button(text="Нет доступных", callback_data="noop")
    kb.adjust(2)
    return kb

def _files_kb(mid: int, chat_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Готово", callback_data=f"quick:files_done:{mid}:{chat_id}")
    b.button(text="🚫 Нет файлов", callback_data=f"quick:no_files:{mid}:{chat_id}")
    b.adjust(2)
    return b.as_markup()

async def _publish_card_and_notify(
    m: Message, mid: int, group_chat_id: int,
    title: str, deadline_ts: Optional[int],
    difficulty_label: str, difficulty: int,
    assignee_tg_id: int, assignee_label: Optional[str],
    author_username: Optional[str] = None
):
    assignee_html = _mention(assignee_tg_id, assignee_label or f"id{assignee_tg_id}")
    by = f"@{author_username or 'без_ника'}"
    card = (
        f"📌 <b>Новая миссия!</b>\n"
        f"От: {by} → Для: {assignee_html}\n"
        f"🎯 {title}\n"
        f"🕒 Дедлайн: {_fmt_deadline(deadline_ts)}\n"
        f"⚡ Сложность: {difficulty_label} (+{difficulty})"
    )
    is_admin = await is_admin_fn(m.from_user.id)
    await m.bot.send_message(group_chat_id, card, reply_markup=_mission_actions_kb(mid, is_admin), parse_mode=ParseMode.HTML)

    ok_dm = await _notify_assignee(m.bot, assignee_tg_id, card)
    if not ok_dm:
        me = await m.bot.get_me()
        link = f"https://t.me/{me.username}?start=go"
        await m.bot.send_message(
            group_chat_id,
            f"⚠️ {assignee_html}, открой бота в личке, чтобы получать уведомления: {link}",
            parse_mode=ParseMode.HTML,
        )

# ───────── FSM ─────────

class QuickAssign(StatesGroup):
    awaiting_text = State()
    awaiting_files = State()
    awaiting_text_for_selected = State()
    picking_user = State()

# ───────── Меню назначения ─────────

@router.message(F.text == "➕ Дать миссию")
@router.message(F.text.regexp(r"(?i)^/?дать\s+(?:миссию|задание)$"))
async def menu_add(m: Message, state: FSMContext):
    await ensure_user(m.from_user)
    await state.update_data(group_chat_id=m.chat.id)
    await m.reply("Выберите способ выдачи:", reply_markup=_assign_menu_reply_kb())

@router.message(F.text == "🙈 Скрыть меню")
async def hide_menu(m: Message, state: FSMContext):
    await m.reply("Спрятал меню.", reply_markup={"remove_keyboard": True, "selective": True})

@router.message(F.text == "✍️ Текстом")
async def quick_add_text(m: Message, state: FSMContext):
    await state.set_state(QuickAssign.awaiting_text)
    await m.reply(
        "Напишите 1 сообщением: <code>@исполнитель что делать когда</code>\n"
        "Можно без @: <code>Витя сведи трек до завтра 20:00</code>",
        parse_mode=ParseMode.HTML,
    )

@router.message(F.text == "👤 Выбрать исполнителя")
async def pick_user_open(m: Message, state: FSMContext):
    await state.set_state(QuickAssign.picking_user)
    users, _total = await list_users(page=0, page_size=100)
    kb = _build_user_picker_simple(users)
    await m.reply("Кому даём задачу?", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("pick:set:"))
async def pick_user_set(c: CallbackQuery, state: FSMContext):
    try:
        assignee_tg = int(c.data.split(":")[2])
    except Exception:
        with contextlib.suppress(TelegramBadRequest):
            await c.answer("Ошибка выбора исполнителя", show_alert=True)
        return
    await state.update_data(assignee_tg=assignee_tg)
    await state.set_state(QuickAssign.awaiting_text_for_selected)
    await c.message.reply(
        "Опишите задачу 1 сообщением (без @):\nНапример: <code>свести трек OG Flow до завтра 20:00</code>",
        parse_mode=ParseMode.HTML,
    )
    with contextlib.suppress(TelegramBadRequest):
        await c.answer()

# ───────── Создание миссии из текста ─────────

async def _create_mission_from_text(m: Message, text: str, group_chat_id: int, pre_user: Optional[Dict]):
    original = text or ""
    first_token = (original.split() + [""])[0]
    text_for_parse = original if not pre_user else original[len(first_token):].strip()

    parsed = await assistant_summarize_quick(text_for_parse)

    if not parsed.get("is_valid", True):
        penalty = -1
        await karma_svc.add_karma_tg(m.from_user.id, penalty, f"Некорректная задача: {parsed.get('violation')}")
        aid = await create_appeal(m.from_user.id, original, parsed.get("violation", ""), penalty)
        await m.reply(f"⛔️ Отклонено: {parsed.get('violation')} (−1 карма). Апелляция #{aid}")
        return

    if pre_user:
        assignee_tg_id = int(pre_user["tg_id"])
        assignee_label = pre_user.get("full_name") or f"id{assignee_tg_id}"
        parsed["assignee_username"] = None
    else:
        assignee_uname = (parsed.get("assignee_username") or "").strip()
        if assignee_uname and not assignee_uname.startswith("@"):
            assignee_uname = "@" + assignee_uname
        if assignee_uname:
            u = await find_user_by_username(assignee_uname.lstrip("@"))
            if not u:
                await m.reply(f"{assignee_uname} не найден. Пусть нажмёт /start.")
                return
            assignee_tg_id = u["tg_id"]
            assignee_label = assignee_uname
        else:
            assignee_tg_id = m.from_user.id
            assignee_label = f"@{m.from_user.username}" if m.from_user.username else f"id{m.from_user.id}"

    mid = await create_mission(
        title=parsed.get("title", "Миссия"),
        description=parsed.get("description_og", ""),
        author_tg_id=m.from_user.id,
        assignees=[assignee_tg_id],
        deadline_ts=parsed.get("deadline_ts"),
        difficulty=int(parsed.get("difficulty_points", 1)),
        difficulty_label=parsed.get("difficulty_label", "🟡 Средняя"),
    )
    s = await mission_summary(mid)

    await _publish_card_and_notify(
        m, mid, group_chat_id,
        title=s["mission"]["title"],
        deadline_ts=s["mission"].get("deadline_ts"),
        difficulty_label=s["mission"].get("difficulty_label", "🟡 Средняя"),
        difficulty=int(s["mission"].get("difficulty", 1)),
        assignee_tg_id=assignee_tg_id,
        assignee_label=assignee_label,
        author_username=m.from_user.username,
    )

    await m.reply("Есть файлы для карточки? Пришлите сюда и нажмите «Готово».",
                  reply_markup=_files_kb(mid, group_chat_id))
    return mid

@router.message(QuickAssign.awaiting_text_for_selected)
async def add_from_selected(m: Message, state: FSMContext):
    st = await state.get_data()
    group_chat_id = st.get("group_chat_id", m.chat.id)
    assignee_tg_id = int(st["assignee_tg"])
    pre_user = {"tg_id": assignee_tg_id, "full_name": None}
    await _create_mission_from_text(m, m.text or "", group_chat_id, pre_user)
    await state.update_data(files=[], group_chat_id=group_chat_id)
    await state.set_state(QuickAssign.awaiting_files)

@router.message(QuickAssign.awaiting_text)
async def quick_parse_and_publish(m: Message, state: FSMContext):
    st = await state.get_data()
    group_chat_id = st.get("group_chat_id", m.chat.id)
    original = m.text or ""
    first = (original.split() + [""])[0]
    pre_user = await find_user_by_name_prefix(first)
    await _create_mission_from_text(m, original, group_chat_id, pre_user)
    await state.update_data(files=[], group_chat_id=group_chat_id)
    await state.set_state(QuickAssign.awaiting_files)

# ───────── Файлы отчёта ─────────

@router.message(QuickAssign.awaiting_files)
async def collect_files(m: Message, state: FSMContext):
    st = await state.get_data()
    files = st.get("files", [])
    kind, file_id = None, None
    caption = m.caption or m.text or ""
    if m.photo:
        kind, file_id = "photo", m.photo[-1].file_id
    elif getattr(m, "video", None):
        kind, file_id = "video", m.video.file_id
    elif getattr(m, "audio", None):
        kind, file_id = "audio", m.audio.file_id
    elif m.document:
        kind, file_id = "document", m.document.file_id

    if kind and file_id:
        files.append({"kind": kind, "file_id": file_id, "caption": caption})
        await state.update_data(files=files)
        await m.answer("✅ Принял. Ещё что-то? Или «Готово».")
    else:
        await m.answer("Пришлите фото/видео/аудио/док — или нажмите «Готово».")

@router.callback_query(F.data.regexp(r"^quick:(files_done|no_files):(\d+):(-?\d+)$"))
async def finalize_files(c: CallbackQuery, state: FSMContext):
    _, mid_s, chat_s = c.data.split(":")[1:]
    mid, group_chat_id = int(mid_s), int(chat_s)
    st = await state.get_data()
    files = st.get("files", [])
    for f in files:
        try:
            cap = f"📎 Файл по миссии #{mid}\n{f.get('caption') or ''}".strip()
            if f["kind"] == "photo":
                await c.bot.send_photo(group_chat_id, f["file_id"], caption=cap)
            elif f["kind"] == "video":
                await c.bot.send_video(group_chat_id, f["file_id"], caption=cap)
            elif f["kind"] == "audio":
                await c.bot.send_audio(group_chat_id, f["file_id"], caption=cap)
            elif f["kind"] == "document":
                await c.bot.send_document(group_chat_id, f["file_id"], caption=cap)
        except Exception as e:
            logger.info(f"[QUICK] send file failed: {e}")
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await c.answer("Готово ✅")

# ───────── Отчёты ─────────

class ReportFlow(StatesGroup):
    collecting = State()

def _report_kb(mid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить", callback_data=f"report:send:{mid}")
    kb.button(text="✖️ Отмена", callback_data=f"report:cancel:{mid}")
    kb.adjust(2)
    return kb.as_markup()

@router.callback_query(F.data.regexp(r"^m:(\d+):report$"))
async def mission_report_start(c: CallbackQuery, state: FSMContext):
    mid = int(c.data.split(":")[1])
    await state.clear()
    await state.update_data(mid=mid, report_items=[], group_chat_id=c.message.chat.id)
    await c.message.reply(
        "Отправьте материалы отчёта (фото/видео/аудио/док). Текстовые заметки буду скрывать.\n"
        "Когда закончите — нажмите «Отправить».",
        reply_markup=_report_kb(mid),
    )
    with contextlib.suppress(TelegramBadRequest):
        await c.answer()
    await state.set_state(ReportFlow.collecting)

@router.message(ReportFlow.collecting)
async def mission_report_collect(m: Message, state: FSMContext):
    st = await state.get_data()
    items = st.get("report_items", [])
    entry = {"kind": None, "file_id": None, "text": m.text or (m.caption or "")}

    if m.photo:
        entry["kind"], entry["file_id"] = "photo", m.photo[-1].file_id
    elif getattr(m, "video", None):
        entry["kind"], entry["file_id"] = "video", m.video.file_id
    elif m.audio:
        entry["kind"], entry["file_id"] = "audio", m.audio.file_id
    elif m.document:
        entry["kind"], entry["file_id"] = "document", m.document.file_id
    else:
        entry["kind"] = "text"

    items.append(entry)
    await state.update_data(report_items=items)

    if entry["kind"] == "text" and not (entry["text"] or "").strip().startswith("📎"):
        await m.reply("✔️ Принял заметку.")
    else:
        await m.answer("✔️ Принял файл для отчёта.")

@router.callback_query(F.data.regexp(r"^report:(send|cancel):(\d+)$"))
async def mission_report_finish(c: CallbackQuery, state: FSMContext):
    action, mid_s = c.data.split(":")[1:]
    mid = int(mid_s)
    st = await state.get_data()
    items = st.get("report_items", [])
    group_chat_id = st.get("group_chat_id")
    await state.clear()

    if action == "cancel":
        await c.message.reply("Отчёт отменён.")
        with contextlib.suppress(TelegramBadRequest):
            await c.answer()
        return

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM assignments WHERE mission_id=? AND assignee_tg_id=?",
            (mid, c.from_user.id),
        )
        row = await cur.fetchone()
        if row:
            await db.execute("UPDATE assignments SET report_json=? WHERE id=?",
                             (json.dumps(items, ensure_ascii=False), row["id"]))
        else:
            await db.execute(
                "INSERT INTO assignments (mission_id, assignee_tg_id, status, report_json, created_at) "
                "VALUES (?,?,?,?,strftime('%s','now'))",
                (mid, c.from_user.id, "assigned", json.dumps(items, ensure_ascii=False)),
            )
        await db.commit()
    finally:
        await db.close()

    await mark_done(mid, c.from_user.id)
    await c.message.reply("✅ Отчёт отправлен на проверку администратору.")
    await _post_report_for_review(c.bot, mid, c.from_user.id, "см. вложения / details в БД")
    with contextlib.suppress(TelegramBadRequest):
        await c.answer()

# ───────── Кнопки карточки ─────────

@router.callback_query(F.data.regexp(r"^m:(\d+):postmenu$"))
async def cb_postpone_menu(c: CallbackQuery):
    _, mid_s, _ = c.data.split(":")
    await c.message.edit_reply_markup(reply_markup=_postpone_menu_kb(int(mid_s)))
    with contextlib.suppress(TelegramBadRequest):
        await c.answer()

@router.callback_query(F.data.regexp(r"^m:(\d+):post:(\d+|cancel)$"))
async def cb_postpone_days(c: CallbackQuery):
    parts = c.data.split(":")
    _, mid_s, _, days_s = parts
    if days_s == "cancel":
        await c.message.edit_reply_markup(reply_markup=_mission_actions_kb(int(mid_s)))
        with contextlib.suppress(TelegramBadRequest):
            await c.answer("Отмена")
        return
    mid = int(mid_s)
    days = max(1, min(3, int(days_s) if days_s.isdigit() else 1))
    penalty = 0 if days == 1 else (-1 if days == 2 else -2)

    ok, msg, new_deadline = await postpone_days(mid, days, c.from_user.id, penalty)
    if not ok:
        with contextlib.suppress(TelegramBadRequest):
            await c.answer(msg, show_alert=True)
        return

    try:
        assignees = await get_assignees_tg(mid)
        people = ", ".join([_mention(x, "исполнитель") for x in assignees]) or "исполнитель"
        await c.message.reply(
            f"⏳ Миссия #{mid}: дедлайн продлён до {_fmt_deadline(new_deadline)}. {penalty:+d} к карме ({people}).",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.debug(f"[POSTPONE BROADCAST] {e}")
    with contextlib.suppress(TelegramBadRequest):
        await c.answer()

@router.callback_query(F.data.regexp(r"^m:(\d+):done$"))
async def mission_done_cb(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    await mark_done(mid, c.from_user.id)
    with contextlib.suppress(TelegramBadRequest):
        await c.answer("✅ Отчёт отправлен на ревью", show_alert=False)
    await _post_report_for_review(c.bot, mid, c.from_user.id, "без текста")

@router.callback_query(F.data.regexp(r"^m:(\d+):cancel$"))
async def mission_cancel_cb(c: CallbackQuery):
    mid = int(c.data.split(":")[1])
    try:
        db = await get_db()
        try:
            cur = await db.execute("SELECT assignee_tg_id FROM assignments WHERE mission_id=?", (mid,))
            ass = [r["assignee_tg_id"] for r in await cur.fetchall()]
            for tg in ass:
                with contextlib.suppress(Exception):
                    await karma_svc.add_karma_tg(tg, -2, "Отмена без причины")
            await db.execute("UPDATE missions SET status='CANCELLED' WHERE id=?", (mid,))
            await db.commit()
        finally:
            await db.close()
        await add_event("cancel", {"mission_id": mid, "by": c.from_user.id})
        await c.message.reply("❌ Миссия отменена (−2 к карме исполнителю).")
        with contextlib.suppress(TelegramBadRequest):
            await c.answer()
    except Exception as e:
        logger.warning(f"[CANCEL] failed: {e}")
        with contextlib.suppress(TelegramBadRequest):
            await c.answer("Не вышло отменить. Напиши админу.", show_alert=True)

# ───────── АДМИН-ПАНЕЛЬ (экран + действия) ─────────

ADMIN_DELETE_PENALTY = -1  # штраф при удалении «со штрафом»

def _admin_target() -> Optional[int]:
    # здесь твоя логика: куда слать отчёты/ревью (чат/личка админа)
    # можно хранить chat_id в конфиге/БД; пока вернём None чтобы не падать
    return None

def _kb_admin_panel(mid: int, performer_id: Optional[int]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if performer_id:
        kb.button(text="✅ Принять отчёт", callback_data=f"review:approve:{mid}:{performer_id}")
        kb.button(text="🔁 На доработку", callback_data=f"review:reject:{mid}:{performer_id}")
        kb.button(text="➕ Карма +1", callback_data=f"admin:karma:+:{performer_id}:1")
        kb.button(text="➖ Карма −1", callback_data=f"admin:karma:-:{performer_id}:1")
        kb.button(text="➕ Карма +5", callback_data=f"admin:karma:+:{performer_id}:5")
        kb.button(text="➖ Карма −5", callback_data=f"admin:karma:-:{performer_id}:5")
    kb.button(text="🗑 Удалить (штраф)", callback_data=f"m:{mid}:delete_penalty:{performer_id or 0}")
    kb.button(text="♻️ Удалить (без штрафа)", callback_data=f"m:{mid}:delete_nopenalty")
    kb.adjust(2, 2, 2)
    return kb.as_markup()

async def _get_mission(mid: int):
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT id, title, difficulty, difficulty_label, assignee_tg_id, author_tg_id, deadline_ts
            FROM missions WHERE id=?
            """,
            (mid,),
        )
        row = await cur.fetchone()
        return row
    finally:
        await db.close()

@router.callback_query(F.data.regexp(r"^m:(\d+):admin$"))
async def open_admin_panel(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только для админа.", show_alert=True)
        return

    mid = int(c.data.split(":")[1])
    row = await _get_mission(mid)
    if not row:
        await c.answer("Миссия не найдена", show_alert=True)
        return

    title = row["title"] or f"#{mid}"
    perf = row["assignee_tg_id"]

    text = (
        f"👑 <b>Админ-панель</b> · Миссия #{mid}\n"
        f"«{title}»\n"
        f"Сложность: {row['difficulty'] or 1} ({row.get('difficulty_label') or ''})"
    )
    await c.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_kb_admin_panel(mid, perf))
    with contextlib.suppress(Exception):
        await c.answer()

# — ревью: принять / на доработку —

@router.callback_query(F.data.regexp(r"^review:approve:(\d+):(\d+)$"))
async def review_approve(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только для админа.", show_alert=True)
        return

    mid = int(c.data.split(":")[2])
    performer = int(c.data.split(":")[3])

    row = await _get_mission(mid)
    if not row:
        await c.answer("Миссия не найдена", show_alert=True)
        return

    pts = int(row["difficulty"] or 1)
    await karma_svc.add_karma_tg(performer, pts, f"Миссия #{mid}: принято")
    await set_status(mid, "DONE")
    await add_event("review_ok", {"mission_id": mid, "by": c.from_user.id, "performer": performer, "reward": pts})

    text = line_done(user_name=f"id{performer}", points=pts)
    try:
        await c.message.edit_text(f"🏆 {text}  (#{mid})")
    except Exception:
        await c.answer("Принято", show_alert=False)

@router.callback_query(F.data.regexp(r"^review:reject:(\d+):(\d+)$"))
async def review_reject(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только для админа.", show_alert=True)
        return

    mid = int(c.data.split(":")[2])
    performer = int(c.data.split(":")[3])

    pen = rework_penalty()
    await karma_svc.add_karma_tg(performer, pen, f"Миссия #{mid}: на доработку")
    await set_status(mid, "REWORK")
    await add_event("review_rework", {"mission_id": mid, "by": c.from_user.id, "performer": performer, "penalty": pen})

    text = line_rework(user_name=f"id{performer}", penalty=pen)
    try:
        await c.message.edit_text(f"🔁 {text}  (#{mid})")
    except Exception:
        await c.answer("Отправлено на доработку", show_alert=False)

# — удаление: со штрафом / без штрафа —

@router.callback_query(F.data.regexp(r"^m:(\d+):delete_penalty:(\d+)$"))
async def delete_with_penalty(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только для админа.", show_alert=True)
        return

    parts = c.data.split(":")
    mid = int(parts[1])
    performer = int(parts[3]) if len(parts) > 3 else 0

    db = await get_db()
    try:
        await db.execute("UPDATE missions SET status='CANCELLED_ADMIN' WHERE id=?", (mid,))
        await db.execute(
            "INSERT INTO events (kind, payload, created_at) VALUES ('admin_delete_penalty', json_object('mission_id', ?, 'by', ?, 'performer', ?), strftime('%s','now'))",
            (mid, c.from_user.id, performer),
        )
        await db.commit()
    finally:
        await db.close()

    if performer:
        await karma_svc.add_karma_tg(performer, ADMIN_DELETE_PENALTY, f"Миссия #{mid}: удалена админом")

    try:
        suffix = f" (−{abs(ADMIN_DELETE_PENALTY)} кармы исполнителю)" if performer else ""
        await c.message.edit_text(f"🗑 Миссия #{mid} удалена админом со штрафом{suffix}.")
    except Exception:
        await c.answer("Удалено (со штрафом).", show_alert=False)

@router.callback_query(F.data.regexp(r"^m:(\d+):delete_nopenalty$"))
async def delete_no_penalty(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только для админа.", show_alert=True)
        return

    mid = int(c.data.split(":")[1])

    db = await get_db()
    try:
        await db.execute("UPDATE missions SET status='CANCELLED_ADMIN' WHERE id=?", (mid,))
        await db.execute(
            "INSERT INTO events (kind, payload, created_at) VALUES ('admin_delete', json_object('mission_id', ?, 'by', ?), strftime('%s','now'))",
            (mid, c.from_user.id),
        )
        await db.commit()
    finally:
        await db.close()

    try:
        await c.message.edit_text(f"♻️ Миссия #{mid} удалена админом без штрафа.")
    except Exception:
        await c.answer("Удалено.", show_alert=False)

# — быстрая карма от админа —

@router.callback_query(F.data.regexp(r"^admin:karma:(\+|\-):(\d+):(1|5)$"))
async def admin_adjust_karma(c: CallbackQuery):
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только для админа.", show_alert=True)
        return

    parts = c.data.split(":")
    sign = parts[2]
    uid = int(parts[3])
    amount = int(parts[4])

    delta = amount if sign == "+" else -amount
    await karma_svc.add_karma_tg(uid, delta, f"Админ-коррекция {delta:+d}")

    with contextlib.suppress(Exception):
        await c.answer(f"Карма {delta:+d} применена.", show_alert=False)
