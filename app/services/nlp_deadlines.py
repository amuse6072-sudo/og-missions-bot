from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import os

"""
Парсер дедлайнов из естественных фраз:
— "сегодня", "завтра", "послезавтра"
— "срочно", "до конца рабочего дня", "к вечеру", "к обеду", "утром"
— явное время HH:MM
— даты dd.mm[.yy(yy)] или yyyy-mm-dd
Рабочий день/таймзона берутся из .env (если заданы), иначе дефолты.
"""

__all__ = ["parse_deadline", "text_due_today", "fmt_dt_local"]

ENV_TZ = os.getenv("TZ", "Europe/Kyiv")
ENV_START_H = int(os.getenv("WORKDAY_START_HOUR", "10"))
ENV_END_H = int(os.getenv("WORKDAY_END_HOUR", "20"))

DEFAULT_TZ = ZoneInfo(ENV_TZ)
DEFAULT_WORK_START = ENV_START_H
DEFAULT_WORK_END = ENV_END_H

RU_DAY_WORDS = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
PHRASE_TO_HOUR = {
    "до конца рабочего дня": DEFAULT_WORK_END,
    "к концу дня": DEFAULT_WORK_END,
    "к вечеру": 19,
    "к обеду": 13,
    "утром": 11,
    "срочно": DEFAULT_WORK_END,
    "asap": DEFAULT_WORK_END,
}

TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
DATE_DOT_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")
DATE_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

def _apply_tz(dt: datetime, tz: ZoneInfo) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)

def parse_deadline(
    text: str,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
    work_start: int = DEFAULT_WORK_START,
    work_end: int = DEFAULT_WORK_END,
) -> int:
    tz = tz or DEFAULT_TZ
    now = _apply_tz(now or datetime.now(tz), tz)
    s = (text or "").lower()

    # явное время HH:MM (с возможным сдвигом по "сегодня/завтра/послезавтра")
    m = TIME_RE.search(s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        add_days = 0
        for k, d in RU_DAY_WORDS.items():
            if k in s:
                add_days = d
                break
        d_ = (now + timedelta(days=add_days)).date()
        return int(_apply_tz(datetime(d_.year, d_.month, d_.day, hh, mm), tz).timestamp())

    # ISO YYYY-MM-DD
    m = DATE_ISO_RE.search(s)
    if m:
        yyyy, mm, dd = map(int, m.groups())
        return int(_apply_tz(datetime(yyyy, mm, dd, work_end, 0), tz).timestamp())

    # D.M[.Y]
    m = DATE_DOT_RE.search(s)
    if m:
        dd, mm = int(m.group(1)), int(m.group(2))
        yyyy = int(m.group(3)) if m.group(3) else now.year
        if yyyy < 100:
            yyyy += 2000
        return int(_apply_tz(datetime(yyyy, mm, dd, work_end, 0), tz).timestamp())

    # относительные дни
    for k, d in RU_DAY_WORDS.items():
        if k in s:
            tgt = now + timedelta(days=d)
            return int(_apply_tz(datetime(tgt.year, tgt.month, tgt.day, work_end, 0), tz).timestamp())

    # фразы "срочно/к вечеру/к обеду/до конца дня"
    for phrase, hour in PHRASE_TO_HOUR.items():
        if phrase in s:
            return int(_apply_tz(datetime(now.year, now.month, now.day, hour, 0), tz).timestamp())

    # дефолт: сегодня к концу дня
    return int(_apply_tz(datetime(now.year, now.month, now.day, work_end, 0), tz).timestamp())

def text_due_today(text: str) -> bool:
    s = (text or "").lower()
    if any(w in s for w in ("срочно", "сегодня", "к вечеру", "до конца рабочего дня", "к концу дня", "asap")):
        return True
    if TIME_RE.search(s) and not any(word in s for word in ("завтра", "послезавтра")):
        return True
    return False

def fmt_dt_local(ts: int, fmt: str = "%d.%m %H:%M", tz: ZoneInfo | None = None) -> str:
    tz = tz or DEFAULT_TZ
    dt = datetime.fromtimestamp(int(ts), tz)
    return dt.strftime(fmt)
