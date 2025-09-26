# app/utils/time.py
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── TZ (Europe/Kyiv по умолчанию) ──────────────────────────────────────────────
_TZ_NAME = (
    os.getenv("TZ")
    or os.getenv("TIMEZONE")
    or os.getenv("TZ_NAME")
    or "Europe/Kyiv"
)

def _get_tz():
    try:
        from zoneinfo import ZoneInfo  # py>=3.9
        return ZoneInfo(_TZ_NAME)
    except Exception:
        try:
            from dateutil import tz  # type: ignore
            return tz.gettz(_TZ_NAME) or timezone.utc
        except Exception:
            return timezone.utc

TZ = _get_tz()

# ── Базовые хелперы ────────────────────────────────────────────────────────────
def now_dt() -> datetime:
    return datetime.now(TZ)

def now_ts() -> int:
    return int(now_dt().timestamp())

def fmt_dt(ts: int, fmt: str = "%d.%m %H:%M") -> str:
    try:
        return datetime.fromtimestamp(int(ts), TZ).strftime(fmt)
    except Exception:
        return str(ts)

# короткий алиас, если где-то используется
def fmt(ts: int) -> str:
    return fmt_dt(ts)

# ── Парсер дедлайнов из строки ─────────────────────────────────────────────────
def parse_iso_or_date(s: Optional[str]) -> Optional[int]:
    """
    Принимает:
      • ISO: 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM', 'YYYY-MM-DD HH:MM'
      • 'DD.MM' (текущий год, 23:59)
      • 'DD.MM.YYYY' (23:59)
    Возвращает локальный timestamp (TZ).
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None

    # 1) ISO (datetime.fromisoformat)
    try:
        s_iso = s.replace(" ", "T") if (" " in s and "T" not in s) else s
        dt = datetime.fromisoformat(s_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return int(dt.timestamp())
    except Exception:
        pass

    # 2) DD.MM or DD.MM.YYYY → 23:59
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", s)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = m.group(3)
        if year:
            year = int(year)
            if year < 100:
                year += 2000
        else:
            year = now_dt().year
        try:
            dt = datetime(year, month, day, 23, 59, tzinfo=TZ)
            return int(dt.timestamp())
        except Exception:
            return None

    # 3) YYYY-MM-DD → 23:59
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        try:
            dt = datetime(year, month, day, 23, 59, tzinfo=TZ)
            return int(dt.timestamp())
        except Exception:
            return None

    return None

# ── Доп. утилиты (на случай использования в других местах) ─────────────────────
def start_of_day(ts: Optional[int] = None) -> int:
    d = datetime.fromtimestamp(ts if ts is not None else now_ts(), TZ).date()
    return int(datetime(d.year, d.month, d.day, 0, 0, tzinfo=TZ).timestamp())

def end_of_day(ts: Optional[int] = None) -> int:
    d = datetime.fromtimestamp(ts if ts is not None else now_ts(), TZ).date()
    return int(datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ).timestamp())
