# app/handlers/ui.py — FINAL

from __future__ import annotations
from typing import Optional, Tuple, List, Dict, Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode, ContentType
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app.keyboards import (
    main_menu, add_menu_kb, build_user_picker_kb, my_mission_kb,
    confirm_assign_kb, pagination, mission_actions, postpone_menu_kb,
    review_kb,
)
from app.services import missions_service as ms
from app.services.missions_service import (
    is_admin as is_admin_fn, ensure_user, create_mission,
    find_user_by_username, set_status,
)
from app.services.ranking import leaderboard_text, address_for
from app.services.ai_assistant import assistant_summarize_quick, is_household_task
from app.services.state import update_state, get_state, pop_state_key
from app.utils.time import fmt_dt
from app.services.karma import apply_decline_penalty
from app.config import settings
from app.db import get_db

router = Router()

# Кнопки-надписи меню, которые приходят как обычный текст — их нельзя перехватывать общим текстовым хендлером
MENU_BUTTONS = {
    "👑 Админ-панель",
    "🎯 Мои миссии",
    "🗂 Все миссии",
    "🏁 Таблица кармы",
    "➕ Дать миссию",
}

# ───────────────── helpers ─────────────────────────────────────────────────────

def _clamp_pts(x: Optional[int]) -> int:
    try:
        v = int(x or 1)
    except Exception:
        v = 1
    return max(1, min(5, v))

def _to_int_or_none(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None

def _resolve_group_id() -> Optional[int]:
    gid = getattr(settings, "REPORT_CHAT_ID", None) if hasattr(settings, "REPORT_CHAT_ID") else None
    if gid is not None:
        try:
            return int(str(gid).strip())
        except Exception:
            pass
    # fallback — лучше явно задать REPORT_CHAT_ID
    aid = getattr(settings, "ADMIN_USER_ID", None) if hasattr(settings, "ADMIN_USER_ID") else None
    try:
        return int(str(aid).strip()) if aid is not None else None
    except Exception:
        return None

def _resolve_admin_id() -> Optional[int]:
    aid = getattr(settings, "ADMIN_USER_ID", None) if hasattr(settings, "ADMIN_USER_ID") else None
    if aid is None:
        return None
    try:
        return int(str(aid).strip())
    except Exception:
        return None

async def _display_by_tg(tg_id: int) -> str:
    from sqlite3 import OperationalError
    db = await get_db()
    try:
        try:
            cur = await db.execute(
                "SELECT username, full_name, COALESCE(active,1) AS active FROM users WHERE tg_id = ?",
                (tg_id,),
            )
            row = await cur.fetchone()
            if not row:
                return f"id{tg_id}"
            d = dict(row)
            act = int(d.get("active", 1) or 1)
            tag = "" if act == 1 else " (архив)"
            if d.get("username"):
                return f"@{d['username']}{tag}"
            if d.get("full_name"):
                return f"{d['full_name']}{tag}"
            return f"id{tg_id}{tag}"
        except OperationalError:
            cur = await db.execute("SELECT username, full_name FROM users WHERE tg_id = ?", (tg_id,))
            row = await cur.fetchone()
            if not row:
                return f"id{tg_id}"
            d = dict(row)
            if d.get("username"):
                return f"@{d['username']}"
            if d.get("full_name"):
                return f"{d['full_name']}"
            return f"id{tg_id}"
    finally:
        await db.close()

async def _mission_row(mid: int) -> Optional[Dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT m.id, m.title, m.status, m.deadline_ts, m.author_tg_id, m.difficulty,
                   a.assignee_tg_id
            FROM missions m
            LEFT JOIN assignments a ON a.mission_id = m.id
            WHERE m.id = ?
            """,
            (mid,)
        )
        r = await cur.fetchone()
        return dict(r) if r else None
    finally:
        await db.close()

async def _list_user_active_missions(tg_id: int) -> List[Dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT m.id, m.title, m.status, m.deadline_ts
            FROM missions m
            JOIN assignments a ON a.mission_id = m.id
            WHERE a.assignee_tg_id = ?
              AND COALESCE(m.status,'') NOT IN ('DONE','CANCELLED','CANCELLED_ADMIN','DECLINED')
            ORDER BY m.id DESC
            """,
            (tg_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()

async def _list_all_missions(page: int, page_size: int = 10) -> Tuple[List[Dict], int]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) AS cnt FROM missions")
        total = int((await cur.fetchone())["cnt"])
        cur = await db.execute(
            """
            SELECT m.id, m.title, m.status, m.deadline_ts, m.author_tg_id, m.difficulty,
                   a.assignee_tg_id
            FROM missions m
            LEFT JOIN assignments a ON a.mission_id = m.id
            ORDER BY m.id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, page * page_size)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows], total
    finally:
        await db.close()

async def _notify_multi(bot, user_ids: List[int], text: str):
    for uid in set([u for u in user_ids if u]):
        try:
            await bot.send_message(uid, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"[notify] {uid} -> {e}")

# безопасный вызов ассистента: всегда возвращает dict
async def _safe_assistant_quick(text: str) -> Dict[str, Any]:
    try:
        parsed = await assistant_summarize_quick(text)
    except Exception as e:
        logger.opt(exception=True).error(f"[assistant_summarize_quick] fail: {e}")
        parsed = None
    if not isinstance(parsed, dict):
        parsed = {}
    title = (parsed.get("title") or (text or "Миссия"))[:100]
    description_og = (parsed.get("description_og") or (text or "").strip() or "Двигаем по-OG.")[:500]
    deadline_ts = parsed.get("deadline_ts")
    try:
        pts = int(parsed.get("difficulty_points") or 2)
    except Exception:
        pts = 2
    difficulty_label = parsed.get("difficulty_label") or ("🟡 Средняя" if pts == 2 else f"{pts}/5")
    assignee_username = parsed.get("assignee_username")
    return {
        "title": title,
        "description_og": description_og,
        "deadline_ts": deadline_ts,
        "difficulty_points": pts,
        "difficulty_label": difficulty_label,
        "assignee_username": assignee_username,
    }

# ─────────── Посты в группу ───────────────────────────────────────────────────

async def _post_new_mission_to_group(mid: int, creator_tg: int, assignee_tg: int, title: str, deadline_ts: Optional[int], pts: int, bot) -> None:
    gid = _resolve_group_id()
    if not gid:
        return
    who = await _display_by_tg(creator_tg)
    whom = await address_for(assignee_tg)
    dl = fmt_dt(deadline_ts, "%d.%m %H:%M") if deadline_ts else "—"
    txt = (
        f"🆕 <b>Новая движуха</b>\n"
        f"{who} закинул квест для {whom}: «{title}»\n"
        f"⏰ Дедлайн: {dl}\n"
        f"💸 Кармочка за выполнено: +{pts}"
    )
    try:
        await bot.send_message(gid, txt, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"[group new] {e}")

async def _post_assignment_to_group(mid: int, creator_tg: int, assignee_tg: int, title: str, deadline_ts: Optional[int], pts: int, bot) -> None:
    gid = _resolve_group_id()
    if not gid:
        return
    who = await _display_by_tg(creator_tg)
    whom = await address_for(assignee_tg)
    dl = fmt_dt(deadline_ts, "%d.%m %H:%M") if deadline_ts else "—"
    txt = (
        f"🎯 <b>Квест принят</b>\n"
        f"{whom} ворвался в «{title}» от {who}\n"
        f"⏰ Дедлайн: {dl}\n"
        f"💰 За успех капнет: +{pts} кармы"
    )
    try:
        await bot.send_message(gid, txt, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"[group assign] {e}")

async def _post_decline_to_group(mid: int, creator_tg: int, assignee_tg: int, title: str, penalty: int, bot) -> None:
    gid = _resolve_group_id()
    if not gid:
        return
    who = await _display_by_tg(creator_tg)
    whom = await address_for(assignee_tg)
    txt = (
        f"🚫 <b>Отказ по квесту</b>\n"
        f"{whom} сказал «пас» на «{title}» от {who}\n"
        f"🔻 Штраф: −{abs(penalty)} кармы"
    )
    try:
        await bot.send_message(gid, txt, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"[group decline] {e}")

async def _post_postpone_to_group(mid: int, assignee_tg: int, title: str, new_deadline: Optional[int], penalty: int, bot) -> None:
    gid = _resolve_group_id()
    if not gid:
        return
    whom = await address_for(assignee_tg)
    dl = fmt_dt(new_deadline, "%d.%m %H:%M") if new_deadline else "—"
    pen_txt = "(без штрафа)" if penalty == 0 else f"(штраф {penalty:+d})"
    msg = f"⏳ <b>Перенос</b>\n{whom} сдвинул «{title}» на {dl} {pen_txt}"
    try:
        await bot.send_message(gid, msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"[group postpone] {e}")

async def _post_review_to_group(mid: int, assignee_tg: int, title: str, bot) -> None:
    gid = _resolve_group_id()
    if not gid:
        return
    whom = await address_for(assignee_tg)
    txt = f"🧾 <b>Отчёт загружен</b>\n{whom} отправил отчёт по квесту «{title}». Ждём вердикт админа."
    try:
        await bot.send_message(gid, txt, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"[group review] {e}")

async def _post_done_to_group(mid: int, assignee_tg: int, title: str, bot) -> None:
    gid = _resolve_group_id()
    if not gid:
        return
    whom = await address_for(assignee_tg)
    txt = f"✅ <b>Готово</b>\n{whom} закрыл квест «{title}». Карма начислена."
    try:
        await bot.send_message(gid, txt, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"[group done] {e}")

async def _post_rework_to_group(mid: int, assignee_tg: int, title: str, reason: str, new_deadline: Optional[int], bot) -> None:
    gid = _resolve_group_id()
    if not gid:
        return
    whom = await address_for(assignee_tg)
    dl = fmt_dt(new_deadline, "%d.%m %H:%M") if new_deadline else "—"
    txt = (
        f"♻️ <b>На доработку</b>\n"
        f"{whom}, причина: {reason}\n"
        f"Новый дедлайн: {dl} (без потери кармы)"
    )
    try:
        await bot.send_message(gid, txt, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"[group rework] {e}")

# ─────────── Главное меню / экраны ─────────────────────────────────────────────

async def send_main_menu(bot, chat_id: int, user_tg_id: int, reply_to: Optional[int] = None) -> None:
    admin = await is_admin_fn(user_tg_id)
    kb = main_menu(is_admin=admin)
    await bot.send_message(
        chat_id,
        "🏠 <b>Главное меню</b>",
        reply_to_message_id=reply_to,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )

async def _render_mine(bot, chat_id: int, user_id: int) -> None:
    items = await _list_user_active_missions(user_id)
    if not items:
        await bot.send_message(chat_id, "Пока пусто. Жми «➕ Дать миссию» или лови квесты от братвы.")
        return
    for it in items[:10]:
        mid = it["id"]; title = it["title"]
        dl = fmt_dt(it.get("deadline_ts"), "%d.%m %H:%M") if it.get("deadline_ts") else "—"
        st = (it.get("status") or "IN_PROGRESS").upper()
        st_name = {"IN_PROGRESS":"в процессе", "REVIEW":"на проверке", "REWORK":"на доработке"}.get(st, st.lower())
        txt = f"• #{mid} «{title}»\n⏰ {dl} | статус: {st_name}"
        await bot.send_message(chat_id, txt, reply_markup=my_mission_kb(mid))

@router.callback_query(F.data == "menu:mine")
async def cb_mine(c: CallbackQuery):
    await _render_mine(c.bot, c.message.chat.id, c.from_user.id)
    await c.answer()

@router.message(F.text == "🎯 Мои миссии")
async def msg_mine(m: Message):
    await _render_mine(m.bot, m.chat.id, m.from_user.id)

async def _render_all_page(bot, chat_id: int, page: int) -> None:
    page_size = 10
    rows, total = await _list_all_missions(page=page, page_size=page_size)
    if not rows:
        await bot.send_message(chat_id, "По квестам тишина. Ждём движ.")
        return
    lines = ["🗂 <b>Все миссии</b>"]
    for r in rows:
        a = await _display_by_tg(r["author_tg_id"]) if r.get("author_tg_id") else "—"
        s = await _display_by_tg(r["assignee_tg_id"]) if r.get("assignee_tg_id") else "—"
        st = (r.get("status") or "").upper()
        human = {
            "IN_PROGRESS":"в процессе",
            "REVIEW":"на проверке",
            "REWORK":"на доработке",
            "DONE":"выполнено",
            "CANCELLED":"отменено",
            "DECLINED":"отказ",
            "": "не задан",
        }.get(st, st.lower() or "не задан")
        dl = fmt_dt(r.get("deadline_ts"), "%d.%m %H:%M") if r.get("deadline_ts") else "—"
        lines.append(f"#{r['id']}: {a} → {s} — «{r['title']}» | ⏰ {dl} | {human}")
    kb = pagination("all", page, has_prev=page > 0, has_next=(page + 1) * page_size < total)
    await bot.send_message(chat_id, "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)

@router.callback_query(F.data == "menu:all")
async def cb_all(c: CallbackQuery):
    await _render_all_page(c.bot, c.message.chat.id, page=0)
    await c.answer()

@router.callback_query(F.data.startswith("all:page:"))
async def cb_all_page(c: CallbackQuery):
    _, _, page_s = c.data.split(":"); page = int(page_s)
    await _render_all_page(c.bot, c.message.chat.id, page=page)
    await c.answer()

@router.message(F.text == "🗂 Все миссии")
async def msg_all(m: Message):
    await _render_all_page(m.bot, m.chat.id, page=0)

@router.callback_query(F.data == "menu:home")
async def cb_home(c: CallbackQuery):
    await send_main_menu(c.bot, c.message.chat.id, c.from_user.id)
    await c.answer()

@router.message(F.text == "🏁 Таблица кармы")
@router.callback_query(F.data == "menu:lb")
async def cb_lb(e):
    txt = await leaderboard_text(limit=15)
    if isinstance(e, Message):
        await e.answer(txt, parse_mode=ParseMode.HTML)
    else:
        await e.message.answer(txt, parse_mode=ParseMode.HTML)
        await e.answer()

# ─────────── Админ-панель (ставим ВЫШЕ общего текстового хендлера) ────────────

def _admin_panel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Участники", callback_data="admin:people")
    kb.button(text="⬅️ Назад", callback_data="menu:home")
    kb.adjust(2)
    return kb.as_markup()

@router.message(F.text == "👑 Админ-панель")
@router.callback_query(F.data == "menu:admin")
async def open_admin_panel(e):
    if isinstance(e, Message):
        uid = e.from_user.id; chat_id = e.chat.id
    else:
        uid = e.from_user.id; chat_id = e.message.chat.id
    if not await is_admin_fn(uid):
        txt = "Только для админа."
        if isinstance(e, Message): await e.answer(txt)
        else: await e.answer(txt, show_alert=True)
        return
    text = "👑 <b>Админ-панель</b>\nВыбирай раздел."
    if isinstance(e, Message):
        await e.answer(text, parse_mode=ParseMode.HTML, reply_markup=_admin_panel_kb())
    else:
        await e.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_admin_panel_kb())
        try: await e.answer()
        except: pass

# ─────────── «Дать миссию»: выбор исполнителя → описание → превью → отправка ──

@router.message(F.text == "➕ Дать миссию")
@router.callback_query(F.data == "menu:add")
async def open_add(e):
    await update_state(e.from_user.id, {"add_step": None, "new_user": None, "del_user_wait": False})
    await update_state(e.from_user.id, {"await_ai_text": True, "ai_draft": None, "await_text_task": False, "assignee_for_next": None})

    prompt = (
        "✍️ Опиши квест <b>одним сообщением</b> — можно с @исполнителем и дедлайном.\n"
        "Примеры:\n"
        "• @vitya сведи трек OG Flow до завтра 20:00\n"
        "• Сделать обложку для релиза «Street Tape» к пятнице вечером\n\n"
        "Или сперва выбери исполнителя — увидишь ⚖️карму и 🔥актив."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Выбрать исполнителя", callback_data="add:pick")
    kb.adjust(1)
    if isinstance(e, Message):
        await e.answer(prompt, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
    else:
        await e.message.answer(prompt, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
        try: await e.answer()
        except: pass

@router.callback_query(F.data == "add:pick")
async def cb_add_pick(c: CallbackQuery):
    await update_state(c.from_user.id, {"add_step": None, "new_user": None, "del_user_wait": False})
    users, total = await ms.list_users_with_stats(page=0, page_size=8, pattern=None)
    users = [u for u in users if int(u.get("active", 1)) == 1 and _to_int_or_none(u.get("tg_id")) is not None]
    await update_state(c.from_user.id, {"await_ai_text": True, "await_text_task": False})
    await c.message.answer(
        "Кому закидываем квест? Ниже: имя • ⚖️карма • 🔥актив.",
        reply_markup=build_user_picker_kb(users, 0, total, 8)
    )
    try: await c.answer()
    except: pass

@router.callback_query(F.data.startswith("pick:page:"))
async def cb_pick_page(c: CallbackQuery):
    _, _, page_s = c.data.split(":")
    page = int(page_s)
    users, total = await ms.list_users_with_stats(page=page, page_size=8, pattern=None)
    users = [u for u in users if int(u.get("active", 1)) == 1 and _to_int_or_none(u.get("tg_id")) is not None]
    await c.message.edit_reply_markup(reply_markup=build_user_picker_kb(users, page, total, 8))
    try: await c.answer()
    except: pass

@router.callback_query(F.data.startswith("pick:set:"))
async def cb_pick_set(c: CallbackQuery):
    _, _, uid_s = c.data.split(":")
    assignee_tg = int(uid_s)
    # сохраняем выбранного исполнителя и сразу просим описание
    st = await get_state(c.from_user.id)
    draft = st.get("ai_draft") or {}
    draft["assignee_tg_id"] = assignee_tg
    await update_state(c.from_user.id, {"ai_draft": draft, "await_ai_text": True})

    who = await _display_by_tg(assignee_tg)
    await c.message.answer(
        f"Исполнитель выбран: {who}\n\n"
        f"✍️ Теперь опиши квест <b>одним сообщением</b> — можно указать дедлайн. "
        f"После этого пришлю превью с кнопкой «Пульнуть».",
        parse_mode=ParseMode.HTML
    )
    try: await c.answer()
    except: pass

# ─────────── Приём текста → ИИ-превью → «Пульнуть» ────────────────────────────

@router.message(F.content_type == ContentType.TEXT, flags={"block": False})
async def ai_or_text_capture(m: Message):
    # НЕ трогаем нажатия-кнопки из меню (они приходят как обычный текст)
    if (m.text or "").strip() in MENU_BUTTONS:
        return

    st = await get_state(m.from_user.id)

    # сброс побочных состояний
    if st.get("add_step") or st.get("del_user_wait"):
        await update_state(m.from_user.id, {"add_step": None, "new_user": None, "del_user_wait": False})

    # ждём ИИ-текст?
    if not st.get("await_ai_text"):
        return

    await ensure_user(m.from_user)

    try:
        text = m.text or ""
        assignee_tg = st.get("ai_draft", {}).get("assignee_tg_id")

        # если в тексте @ник — маппим на tg_id
        import re
        m_ass = re.search(r"@([A-Za-z0-9_]{3,32})", text or "")
        if not assignee_tg and m_ass:
            who = await find_user_by_username(m_ass.group(1))
            assignee_tg = who["tg_id"] if who else None

        parsed = await _safe_assistant_quick(text)

        title = parsed["title"]
        og_desc = parsed["description_og"]
        deadline = parsed["deadline_ts"]
        pts = _clamp_pts(parsed["difficulty_points"])
        lab = parsed["difficulty_label"]

        ass_txt = await _display_by_tg(assignee_tg) if assignee_tg else "— (выбери исполнителя)"
        dl_txt = fmt_dt(deadline, "%d.%m %H:%M") if deadline else "—"

        # сохраняем state
        await update_state(m.from_user.id, {
            "ai_draft": {
                **(st.get("ai_draft") or {}),
                "title": title,
                "description_og": og_desc,
                "deadline_ts": deadline,
                "difficulty_points": pts,
                "difficulty_label": lab,
                "assignee_tg_id": assignee_tg,
            },
            "await_ai_text": False
        })

        # клавиатура превью
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Пульнуть на подтверждение", callback_data="ai:confirm")
        kb.button(text="👤 Сменить исполнителя", callback_data="add:pick")
        kb.button(text="❌ Снести", callback_data="ai:cancel")
        kb.adjust(1, 1, 1)

        txt = (
            "🧠 <b>Превью квеста</b>\n\n"
            f"👥 Исполнитель: {ass_txt}\n"
            f"📝 Что делать (OG): «{og_desc}»\n"
            f"⏰ Дедлайн: {dl_txt}\n"
            f"💪 Уровень движа: {lab} (карма: +{pts})\n\n"
            "Если всё норм — жми «Пульнуть на подтверждение» 💥"
        )
        await m.answer(txt, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())

    except Exception as e:
        logger.opt(exception=True).error(f"[ai_or_text_capture fatal] {e}")
        assignee_tg = st.get("ai_draft", {}).get("assignee_tg_id")
        ass_txt = await _display_by_tg(assignee_tg) if assignee_tg else "— (выбери исполнителя)"
        title = (m.text or "Миссия")[:100]
        pts = 2
        dl_txt = "—"
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Пульнуть на подтверждение", callback_data="ai:confirm")
        kb.button(text="👤 Сменить исполнителя", callback_data="add:pick")
        kb.button(text="❌ Снести", callback_data="ai:cancel")
        kb.adjust(1, 1, 1)
        await update_state(m.from_user.id, {
            "ai_draft": {
                **(st.get("ai_draft") or {}),
                "title": title,
                "description_og": title,
                "deadline_ts": None,
                "difficulty_points": pts,
                "difficulty_label": "🟡 Средняя",
            },
            "await_ai_text": False
        })
        await m.answer(
            "🧠 <b>Превью квеста</b>\n\n"
            f"👥 Исполнитель: {ass_txt}\n"
            f"📝 Что делать (OG): «{title}»\n"
            f"⏰ Дедлайн: {dl_txt}\n"
            f"💪 Уровень движа: 🟡 Средняя (карма: +2)\n\n"
            "Если всё норм — жми «Пульнуть на подтверждение».",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.as_markup()
        )

# отмена превью
@router.callback_query(F.data == "ai:cancel")
async def ai_cancel(c: CallbackQuery):
    await pop_state_key(c.from_user.id, "ai_draft", None)
    await pop_state_key(c.from_user.id, "await_ai_text", None)
    await c.message.edit_text("Окей, снесли. Без обид ✌️")
    try: await c.answer()
    except: pass

# отправка квеста исполнителю и в группу
@router.callback_query(F.data == "ai:confirm")
async def ai_confirm(c: CallbackQuery):
    st = await get_state(c.from_user.id)
    parsed = st.get("ai_draft") or {}

    title = parsed.get("title") or "Миссия"
    deadline = parsed.get("deadline_ts")
    pts = _clamp_pts(parsed.get("difficulty_points"))
    assignee_tg: Optional[int] = parsed.get("assignee_tg_id")

    if not assignee_tg:
        ass = (parsed.get("assignee_username") or "").lstrip("@")
        if ass:
            row = await find_user_by_username(ass)
            assignee_tg = row["tg_id"] if row else None
    if not assignee_tg:
        await c.message.answer("Исполнитель не выбран. Выбери в списке:", reply_markup=add_menu_kb())
        try: await c.answer()
        except: pass
        return

    # ЛИМИТ: у исполнителя не больше 10 активных. 11-ю может выдать только админ.
    active = await _list_user_active_missions(assignee_tg)
    is_admin = await is_admin_fn(c.from_user.id)
    if len(active) >= 10 and not is_admin:
        who = await _display_by_tg(assignee_tg)
        await c.message.answer(
            f"⚠️ У {who} уже 10 активных квестов. 11-ю может выдать только админ.",
            parse_mode=ParseMode.HTML
        )
        try: await c.answer("Ограничение по активным миссиям")
        except: pass
        return

    creator_tg = c.from_user.id
    mid = await create_mission(
        title=title,
        description=parsed.get("description_og") or title,
        author_tg_id=creator_tg,
        assignees=[assignee_tg],
        deadline_ts=deadline,
        difficulty=pts,
        difficulty_label=str(pts),
    )

    assignee_display = await _display_by_tg(assignee_tg)
    creator_display = await _display_by_tg(creator_tg)
    dl_txt = fmt_dt(deadline, "%d.%m %H:%M") if deadline else "—"

    # ЛС исполнителю
    try:
        await c.bot.send_message(
            assignee_tg,
            (
                f"🆕 Тебе квест #{mid} от {creator_display}:\n"
                f"«{title}»\n⏰ {dl_txt}\n\n"
                f"Подтверди участие или откажись."
            ),
            reply_markup=confirm_assign_kb(mid),
        )
    except Exception as e:
        logger.error(f"[send to assignee DM] {assignee_tg}: {e}")

    # пост в группу
    await _post_new_mission_to_group(mid, creator_tg, assignee_tg, title, deadline, pts, c.bot)

    await c.message.edit_text(f"Пульнул {assignee_display} запрос на подтверждение. Ждём ответ.")
    await pop_state_key(c.from_user.id, "ai_draft", None)
    try: await c.answer()
    except: pass

# ─────────── Принятие / отказ исполнителем ────────────────────────────────────

@router.callback_query(F.data.startswith("assign:accept:"))
async def assign_accept(c: CallbackQuery):
    _, _, mid_s = c.data.split(":"); mid = int(mid_s)
    row = await _mission_row(mid)
    if not row:
        await c.answer("Квест испарился", show_alert=True); return
    if int(row.get("assignee_tg_id") or 0) != c.from_user.id:
        await c.answer("Подтверждать может только исполнитель", show_alert=True); return

    await set_status(mid, "IN_PROGRESS")
    pts = _clamp_pts(row.get("difficulty"))
    await _post_assignment_to_group(
        mid=mid,
        creator_tg=int(row.get("author_tg_id") or 0),
        assignee_tg=int(row.get("assignee_tg_id") or 0),
        title=row.get("title") or "",
        deadline_ts=row.get("deadline_ts"),
        pts=pts,
        bot=c.bot
    )

    creator = int(row.get("author_tg_id") or 0)
    assignee = int(row.get("assignee_tg_id") or 0)
    await _notify_multi(
        c.bot, [creator, assignee],
        f"✅ Квест #{mid} «{row.get('title') or ''}» принят. Дедлайн: "
        f"{fmt_dt(row.get('deadline_ts'), '%d.%m %H:%M') if row.get('deadline_ts') else '—'}."
    )

    await c.message.edit_text("✅ Принял. Двигаем!")
    try: await c.answer()
    except: pass

@router.callback_query(F.data.startswith("assign:decline:"))
async def assign_decline(c: CallbackQuery):
    _, _, mid_s = c.data.split(":"); mid = int(mid_s)
    row = await _mission_row(mid)
    if not row:
        await c.answer("Квест испарился", show_alert=True); return
    if int(row.get("assignee_tg_id") or 0) != c.from_user.id:
        await c.answer("Отказаться может только исполнитель", show_alert=True); return

    title = row.get("title") or ""
    household = is_household_task(title)
    diff = int(row.get("difficulty") or 2)
    pen = await apply_decline_penalty(c.from_user.id, diff, household)

    await set_status(mid, "DECLINED")

    creator = int(row.get("author_tg_id") or 0)
    assignee = int(row.get("assignee_tg_id") or 0)

    await _notify_multi(
        c.bot, [creator, assignee],
        f"🚫 Отказ по квесту #{mid} «{title}». Штраф исполнителю: {pen:+d} кармы."
    )
    await _post_decline_to_group(mid, creator, assignee, title, pen, c.bot)

    await c.message.edit_text(f"Ок, отказ зафиксирован. Штраф {pen:+d} кармы.")
    try: await c.answer()
    except: pass

# ─────────── «Выполнено» → отчёт → REVIEW ─────────────────────────────────────

@router.callback_query(F.data.startswith("m:") & F.data.endswith(":done"))
async def cb_done_request_report(c: CallbackQuery):
    _, mid_s, _ = c.data.split(":"); mid = int(mid_s)
    row = await _mission_row(mid)
    if not row:
        await c.answer("Квест не найден", show_alert=True); return
    if int(row.get("assignee_tg_id") or 0) != c.from_user.id:
        await c.answer("Отчитывается только исполнитель", show_alert=True); return

    await update_state(c.from_user.id, {"await_report_for_mid": mid})
    await c.message.answer(
        "📎 Кинь отчёт по квесту: фото/видео/док/аудио/голос или текст одним сообщением.\n"
        "После приёма админом карма засчитается."
    )
    try: await c.answer()
    except: pass

_REPORTABLE = {
    ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT,
    ContentType.AUDIO, ContentType.VOICE, ContentType.TEXT
}

@router.message(F.content_type.in_(_REPORTABLE))
async def receive_report(m: Message):
    st = await get_state(m.from_user.id)
    mid = st.get("await_report_for_mid")
    if not mid:
        return  # не ждём отчёт — пропускаем

    row = await _mission_row(int(mid))
    if not row or int(row.get("assignee_tg_id") or 0) != m.from_user.id:
        await pop_state_key(m.from_user.id, "await_report_for_mid", None)
        await m.reply("Квест не найден/не твой."); return

    title = row.get("title") or ""
    creator = int(row.get("author_tg_id") or 0)
    assignee = int(row.get("assignee_tg_id") or 0)

    # статус REVIEW
    await set_status(int(mid), "REVIEW")

    # пост в группу «Отчёт загружен»
    await _post_review_to_group(int(mid), assignee, title, m.bot)

    # копируем отчёт в общий чат
    gid = _resolve_group_id()
    caption = (m.caption or m.text or "").strip()
    cap_group = f"🧾 Отчёт по #{mid} — «{title}»\n{caption}" if caption else f"🧾 Отчёт по #{mid} — «{title}»"
    try:
        if gid:
            await m.bot.copy_message(chat_id=gid, from_chat_id=m.chat.id, message_id=m.message_id, caption=cap_group)
    except Exception as e:
        logger.warning(f"[copy report to group] {e}")

    # админу — сначала медиа, потом кнопки
    admin_id = _resolve_admin_id()
    if admin_id:
        cap_admin = f"🧾 Отчёт на проверку по #{mid} — «{title}»"
        try:
            await m.bot.copy_message(
                chat_id=admin_id,
                from_chat_id=m.chat.id,
                message_id=m.message_id,
                caption=cap_admin
            )
        except Exception as e:
            logger.warning(f"[copy report to admin] {e}")

        # собрать клавиатуру ревью (совместимость сигнатур)
        kb = None
        try:
            kb = review_kb(int(mid), admin_id)  # современная сигнатура (mid, uid)
        except TypeError:
            try:
                kb = review_kb(int(mid))  # старая сигнатура (mid)
            except Exception:
                kb = None
        except Exception:
            kb = None

        if kb is None:
            kbld = InlineKeyboardBuilder()
            kbld.button(text="✅ Принять", callback_data=f"review:approve:{mid}")
            kbld.button(text="❌ Отклонить", callback_data=f"review:reject:{mid}")
            kbld.adjust(2)
            kb = kbld.as_markup()

        try:
            await m.bot.send_message(
                admin_id,
                f"🔍 Проверка отчёта по #{mid} — «{title}»\nВыберите действие:",
                reply_markup=kb
            )
        except Exception as e:
            logger.warning(f"[send review buttons to admin] {e}")
    else:
        logger.warning("[review] ADMIN_USER_ID is not set — модерация недоступна")

    await _notify_multi(m.bot, [creator, assignee], f"🧾 Отчёт по квесту #{mid} отправлен на проверку.")
    await pop_state_key(m.from_user.id, "await_report_for_mid", None)

# ─────────── Ревью админом: принять/отклонить ─────────────────────────────────

def _is_review_approve(data: str) -> bool:
    return data.startswith("rev:approve:") or data.startswith("review:approve:")

def _is_review_reject(data: str) -> bool:
    return data.startswith("rev:reject:") or data.startswith("review:reject:")

def _parse_mid_from_review(data: str) -> Optional[int]:
    # допускаем: "review:approve:<mid>" или "review:approve:<mid>:<uid>" или "rev:approve:<mid>"
    parts = data.split(":")
    try:
        if len(parts) >= 3 and parts[0] in ("review", "rev"):
            return int(parts[2])
        for p in reversed(parts):
            if p.isdigit():
                return int(p)
    except Exception:
        return None
    return None

@router.callback_query(F.data.func(_is_review_approve))
async def cb_review_approve(c: CallbackQuery):
    mid = _parse_mid_from_review(c.data)
    if not mid:
        await c.answer("Квест не найден", show_alert=True); return
    row = await _mission_row(mid)
    if not row:
        await c.answer("Квест не найден", show_alert=True); return
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только админ может принять", show_alert=True); return

    # 1) закрываем миссию
    await set_status(mid, "DONE")

    assignee = int(row.get("assignee_tg_id") or 0)
    creator  = int(row.get("author_tg_id") or 0)
    title    = row.get("title") or ""
    dl       = fmt_dt(row.get("deadline_ts"), "%d.%m %H:%M") if row.get("deadline_ts") else "—"

    # 2) начисляем карму (сложность = карма)
    pts = _clamp_pts(row.get("difficulty"))
    awarded = False
    try:
        # основной путь — сервис кармы
        from app.services.karma import add_karma_tg
        await add_karma_tg(assignee, int(pts), f"Миссия #{mid} выполнена")
        awarded = True
    except Exception as e:
        logger.warning(f"[approve] karma service failed: {e}; fallback to SQL")
        # фоллбек — прямое обновление users.karma
        try:
            db = await get_db()
            await db.execute(
                "UPDATE users SET karma = COALESCE(karma,0) + ? WHERE tg_id = ?",
                (int(pts), assignee),
            )
            await db.commit()
            await db.close()
            awarded = True
        except Exception as e2:
            logger.error(f"[approve] SQL karma fallback failed: {e2}")

    # 3) анонсы
    await _post_done_to_group(mid, assignee, title, c.bot)
    plus_txt = f"+{int(pts)} кармы начислено" if awarded else "карма будет начислена позже"
    await _notify_multi(
        c.bot, [creator, assignee],
        f"✅ Принято: #{mid} «{title}». Дедлайн был: {dl}. {plus_txt}."
    )

    # 4) чистим клавиатуру
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await c.answer("Принято ✅")

@router.callback_query(F.data.func(_is_review_reject))
async def cb_review_reject(c: CallbackQuery):
    mid = _parse_mid_from_review(c.data)
    if not mid:
        await c.answer("Квест не найден", show_alert=True); return
    row = await _mission_row(mid)
    if not row:
        await c.answer("Квест не найден", show_alert=True); return
    if not await is_admin_fn(c.from_user.id):
        await c.answer("Только админ может отклонить", show_alert=True); return

    # просим причину
    await update_state(c.from_user.id, {"await_reject_reason_for_mid": mid})
    await c.message.answer("Укажи причину отклонения (одним сообщением).")
    await c.answer("Жду причину…")

@router.message(F.text, flags={"block": False})
async def take_reject_reason(m: Message):
    st = await get_state(m.from_user.id)
    mid = st.get("await_reject_reason_for_mid")
    if not mid:
        return
    if not await is_admin_fn(m.from_user.id):
        await pop_state_key(m.from_user.id, "await_reject_reason_for_mid", None)
        return

    reason = (m.text or "").strip() or "Причина не указана"
    row = await _mission_row(int(mid))
    if not row:
        await pop_state_key(m.from_user.id, "await_reject_reason_for_mid", None)
        await m.reply("Квест не найден."); return

    assignee = int(row.get("assignee_tg_id") or 0)
    creator  = int(row.get("author_tg_id") or 0)

    # статус REWORK + продление на 1 день без штрафа
    await set_status(int(mid), "REWORK")
    ok, msg, new_dl = await ms.postpone_days(int(mid), 1, assignee, penalty=0)

    await _notify_multi(
        m.bot, [creator, assignee],
        f"♻️ Отклонено модерацией: #{mid} «{row.get('title') or ''}».\nПричина: {reason}\n{msg}"
    )
    await _post_rework_to_group(int(mid), assignee, row.get("title") or "", reason, new_dl, m.bot)

    await pop_state_key(m.from_user.id, "await_reject_reason_for_mid", None)
    try:
        await m.reply("Ок, отправил причину и продлил дедлайн (+1 день, без штрафа).")
    except Exception:
        pass

# ─────────── Перенос (кнопочное меню) ─────────────────────────────────────────

@router.callback_query(F.data.startswith("m:") & F.data.endswith(":postmenu"))
async def cb_postpone_menu(c: CallbackQuery):
    _, mid_s, _ = c.data.split(":"); mid = int(mid_s)
    await c.message.edit_reply_markup(reply_markup=postpone_menu_kb(mid))
    try: await c.answer()
    except: pass

@router.callback_query(F.data.startswith("m:") & F.data.contains(":post:"))
async def cb_postpone_days(c: CallbackQuery):
    parts = c.data.split(":")
    if len(parts) != 4:
        await c.answer("Некорректно", show_alert=True); return
    _, mid_s, _, days_s = parts
    if days_s == "cancel":
        await c.message.edit_reply_markup(reply_markup=mission_actions(int(mid_s)))
        try: await c.answer("Отмена")
        except: pass
        return

    mid = int(mid_s)
    days = max(1, min(3, int(days_s) if days_s.isdigit() else 1))
    # Штраф: +1д → 0; +2д → −1; +3д → −2
    penalty = 0 if days == 1 else -(days - 1)

    row = await _mission_row(mid)
    if not row:
        await c.answer("Квест не найден", show_alert=True); return
    if int(row.get("assignee_tg_id") or 0) != c.from_user.id:
        await c.answer("Переносит только исполнитель", show_alert=True); return

    ok, msg, new_dl = await ms.postpone_days(mid, days, c.from_user.id, penalty)
    if not ok:
        await c.answer(msg, show_alert=True); return

    creator = int(row.get("author_tg_id") or 0)
    assignee = int(row.get("assignee_tg_id") or 0)
    await _notify_multi(
        c.bot, [creator, assignee],
        f"⏳ Перенос по квесту #{mid} «{row.get('title') or ''}»: +{days} дн. "
        f"{'(без штрафа)' if penalty == 0 else f'штраф {penalty:+d}'}."
    )
    await c.message.edit_text(f"Перенёс дедлайн: {msg}")
    await _post_postpone_to_group(mid, assignee, row.get("title") or "", new_dl, penalty, c.bot)
    try: await c.answer()
    except: pass

@router.callback_query(F.data.startswith("m:") & F.data.endswith(":postpone"))
async def cb_postpone_compat(c: CallbackQuery):
    _, mid_s, _ = c.data.split(":"); mid = int(mid_s)
    await c.message.edit_reply_markup(reply_markup=postpone_menu_kb(mid))
    try: await c.answer("Выбери, на сколько дней перенести.")
    except: pass
