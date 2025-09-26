from __future__ import annotations
import asyncio, time
from typing import List
from loguru import logger
from aiogram import Bot
from datetime import datetime
from app.db import get_db
from app.services.missions_service import (
    set_reminder_stage, mark_overdue_and_penalize, get_assignees_tg
)
from app.config import settings

def now_ts() -> int: return int(time.time())

def _fmt(ts: int|None) -> str:
    if not ts: return "не указан"
    try:
        # локальное время чата (Киев задан в ассистенте/окружении)
        return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
    except Exception:
        return "не указан"

STAGES = [
    ("24h", 24*3600, "⏰ 24 часа до дедлайна по «{title}» (до {deadline}). Поднажми, бро."),
    ("5h",   5*3600, "⏰ Осталось 5 часов по «{title}» (до {deadline}). Если не вывозишь — жми «⏳ Перенести» (−1 карма)."),
    ("1h",   1*3600, "⏰ Час до дедлайна по «{title}» (до {deadline}). Финальный спурт!"),
]
CHECK_INTERVAL_SEC = 60

async def _fetch_active_missions():
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT id, title, deadline_ts, reminder_stage, extension_count, status
            FROM missions
            WHERE deadline_ts IS NOT NULL
              AND status IN ('OPEN','IN_PROGRESS','WAIT_REPORT','REVIEW')
        """)
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

async def _send_dm(bot: Bot, tg_ids: List[int], text: str):
    for tg in tg_ids:
        try: await bot.send_message(tg, text)
        except Exception: pass

async def _notify_group(bot: Bot, text: str):
    chat_id = getattr(settings, "REPORT_CHAT_ID", None)
    if chat_id:
        try: await bot.send_message(chat_id, text)
        except Exception: pass

async def start_reminders_loop(bot: Bot):
    logger.info("[REMINDERS] loop started")
    while True:
        try:
            now = now_ts()
            for m in await _fetch_active_missions():
                mid, title = m["id"], m["title"]
                dl = int(m["deadline_ts"] or 0); stage = (m["reminder_stage"] or "").strip()
                left = dl - now

                if left <= 0 and stage != "overdue":
                    pen = await mark_overdue_and_penalize(mid)
                    msg = f"💀 Дедлайн сорван по «{title}». Штраф {pen} к карме."
                    await _send_dm(bot, await get_assignees_tg(mid), msg)
                    await _notify_group(bot, msg)
                    await set_reminder_stage(mid, "overdue")
                    continue

                stage_order = {"":0,"24h":1,"5h":2,"1h":3,"overdue":99}
                cur_idx = stage_order.get(stage, 0)
                for idx,(code,sec,tmpl) in enumerate(STAGES, start=1):
                    if left <= sec and cur_idx < idx:
                        text = tmpl.format(title=title, deadline=_fmt(dl))
                        await _send_dm(bot, await get_assignees_tg(mid), text)
                        await set_reminder_stage(mid, code)
                        break
        except Exception as e:
            logger.exception(f"[REMINDERS] error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SEC)
