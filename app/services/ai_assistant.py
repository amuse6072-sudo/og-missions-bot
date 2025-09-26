from __future__ import annotations
import os, re, json, difflib, unicodedata
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

# ======= Внешние сервисы (если недоступны — работаем без них) =======
try:
    from app.services.ai_client import mission_from_text  # ИИ: title/description/assignee_hint/deadline_text/priority
except Exception:
    mission_from_text = None

try:
    from app.services.nlp_deadlines import parse_deadline as nlp_parse
except Exception:
    nlp_parse = None

# ========= ENV / TZ =========
_TZ = os.getenv("TZ", os.getenv("TIMEZONE", "Europe/Kyiv"))
_ZONE = ZoneInfo(_TZ)
_START = int(os.getenv("WORKDAY_START_HOUR", "9"))
_END   = int(os.getenv("WORKDAY_END_HOUR", "20"))

__all__ = [
    "assistant_summarize_quick",
    "classify",
    "is_household_task",
    "render_street_mission",
    "difficulty_human_label",
]

ASSIGNEE_RE = re.compile(r"@([A-Za-z0-9_]{3,32})")
_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:\.]\s?([0-5]\d)(?!\d)")

def _has_explicit_time(s: Optional[str]) -> bool:
    if not s:
        return False
    return bool(_TIME_RE.search(s))

# ====== Нормализация текста ======
def _norm(s: Optional[str]) -> str:
    return (s or "").strip()

def _normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = s.replace("ё", "е").replace("й", "и")
    return s

def _tokenize(s: str) -> list[str]:
    s = _normalize_text(s)
    return re.findall(r"[a-zа-я0-9]+", s)

# ====== Категории/паттерны для сложности ======
HOUSEHOLD = (
    "вынеси мусор", "вынести мусор", "мусор", "убор", "убрать", "уборка",
    "помыть", "помыть пол", "помыть полы", "мытье полов", "мытьё полов",
    "подмести", "пропылесосить", "посуду", "помыть посуду",
    "унитаз", "раковину", "ванну", "окна", "помыть окна",
    "купить продукты", "закупиться", "магазин",
    "полить цветы", "полей цветы", "цветы",
    "покормить", "корм", "животное", "собаку", "кошку", "агаму", "рыбок",
)

COVER = ("обложк", "cover", "арт", "artwork", "обложка к треку", "дизайн обложки")

RECORD = (
    "записать трек", "записать вокал", "записать куплет",
    "запись трека", "record", "вокал записать"
)

MIX = (
    "свести трек", "свести трэк", "сведение", "сведение трека",
    "микс", "миксдаун", "mix", "mixdown",
    "мастер", "мастеринг", "master", "mastering",
)

BEAT = ("сделать бит", "бит сделать", "биток", "beat", "инструментал")

FULL_TRACK = ("полностью сделать трек", "бит + запись + сведение", "с нуля трек", "фулл трек", "full track")

PUBLISH = (
    "опубликов", "вылож", "залей", "загруз", "на площадк", "на dsp",
    "spotify", "apple music", "yandex music", "boom", "vk music",
)

SNIPPET = ("сниппет", "снип", "тизер", "shorts", "шортс", "reels", "рилс", "шорт")

# Видеопродакшн / клипы / студия
SHOOT_LOCATION = ("отснять локацию", "снять локацию", "локация", "выезд на локацию", "локации")
APPEAR_LOCATION = ("сняться", "снимись", "быть в кадре", "участвовать в съемке", "участвовать в съёмке")
FILMING = ("снимать", "съемка", "съёмка", "снять материал", "наснимай", "наотснимай", "оператор")
EDITING = ("смонтировать", "монтаж", "порезать", "нарезка", "склейка", "видео монтаж", "videomontage")
COLOR = ("цветокор", "color", "color grading", "grading", "покрас", "коррекция цвета")
SCRIPT = ("сценарий", "техзадание", "тз", "раскадровка", "сториборд", "treatment", "идея")
GEAR = ("оборудование", "освет", "свет", "микрофон", "рекордер", "штатив", "стедикам", "гимбал", "аренда техники", "подготовить студию")

_NUM_WORDS = {"два":2,"две":2,"три":3,"четыре":4,"пять":5,"шесть":6,"семь":7,"восемь":8,"девять":9,"десять":10}
_SNIPPET_COUNT_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(сниппет\w*|снип\w*|тизер\w*|шортс?\w*|shorts?|reels?)")
_SNIPPET_WORDCOUNT_RE = re.compile(r"\b(" + "|".join(_NUM_WORDS.keys()) + r")\b\s*(сниппет\w*|снип\w*|тизер\w*|шортс?\w*|shorts?|reels?)")

# ====== Фаззи-матчинг ======
def _fuzzy_contains(text: str, variants: tuple[str, ...], *, threshold: float = 0.78) -> bool:
    toks = _tokenize(text)
    if not toks:
        return False
    windows = []
    for n in (1, 2, 3, 4):
        for i in range(0, len(toks) - n + 1):
            windows.append(" ".join(toks[i:i+n]))
    for v in variants:
        v_norm = " ".join(_tokenize(v))
        if not v_norm:
            continue
        joined = " ".join(toks)
        if v_norm in joined:
            return True
        for w in windows:
            if difflib.SequenceMatcher(None, w, v_norm).ratio() >= threshold:
                return True
    return False

def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    t = _normalize_text(text)
    return any(p in t for p in patterns)

def _count_snippets(text: str) -> int:
    t = _normalize_text(text)
    n = 0
    for m in _SNIPPET_COUNT_RE.finditer(t):
        try:
            n = max(n, int(m.group(1)))
        except Exception:
            pass
    for m in _SNIPPET_WORDCOUNT_RE.finditer(t):
        n = max(n, _NUM_WORDS.get(m.group(1), 0))
    if n == 0 and any(k in t for k in SNIPPET):
        occ = sum(t.count(k) for k in set(SNIPPET))
        n = max(1, min(occ, 5))
    return n

# ====== Сложность ======
def _difficulty_from_text(text: str) -> int:
    """
    Честная шкала 1..5 с приоритетами и фаззи:
      5 — «полный трек»
      4 — сведение/мастеринг, запись
      3 — отснять локацию, съёмка материала, монтаж (не сниппет), цветокор, сценарий/раскадровка, подготовка/свет/оборудование
      2 — обложка, сняться в кадре, сделать бит
      1 — публикация, бытовуха, *N сниппетов = N* (до 5)
    """
    t = _normalize_text(text)

    if _fuzzy_contains(t, FULL_TRACK):
        return 5

    sn = _count_snippets(t)
    if sn > 0:
        return max(1, min(5, sn))

    if _fuzzy_contains(t, SHOOT_LOCATION) and "снятс" not in t:
        return 3
    if _fuzzy_contains(t, APPEAR_LOCATION) and "локац" in t:
        return 2
    if _fuzzy_contains(t, FILMING) and "снятс" not in t:
        return 3
    if _fuzzy_contains(t, EDITING):
        return 3
    if _fuzzy_contains(t, COLOR):
        return 3
    if _fuzzy_contains(t, SCRIPT):
        return 3
    if _fuzzy_contains(t, GEAR):
        return 3 if len(t) > 60 else 2

    if _fuzzy_contains(t, MIX):
        return 4
    if _fuzzy_contains(t, RECORD):
        return 4
    if _fuzzy_contains(t, COVER):
        return 2
    if _fuzzy_contains(t, PUBLISH):
        return 1
    if _fuzzy_contains(t, HOUSEHOLD):
        return 1
    if _fuzzy_contains(t, BEAT):
        return 2

    base = 1
    if any(k in t for k in ("интеграци", "аналит", "скрипт", "бот", "сценари", "съемк", "съёмк", "монтаж", "цветокор")):
        base += 1
    if len(t) > 140:
        base += 1
    return max(1, min(5, base))

def _difficulty_label(points: int) -> str:
    labels = {
        1: "🟢 Лёгкая",
        2: "🟡 Средняя",
        3: "🟠 Выше средней",
        4: "🔴 Тяжёлая",
        5: "🟣 Хардкор",
    }
    return labels.get(max(1, min(5, int(points or 1))), "🟡 Средняя")

def difficulty_human_label(points: int) -> str:
    return _difficulty_label(points)

# ====== Слот времени (утро/вечер/день/ночь) ======
def _fix_slot_time(dt: datetime, slot_hint: Optional[str]) -> datetime:
    if not slot_hint:
        return dt
    s = slot_hint.lower()
    if "утр" in s:
        hh = max(_START, 8)
        if hh < 8 or hh > 11: hh = 10
        return dt.replace(hour=hh, minute=0, second=0, microsecond=0, tzinfo=_ZONE)
    if "вечер" in s:
        hh = min(_END, 21)
        if hh < 18 or hh > 21: hh = 19
        return dt.replace(hour=hh, minute=0, second=0, microsecond=0, tzinfo=_ZONE)
    if "обед" in s or "дн" in s:
        hh = max(_START + 3, 12)
        if hh > 15: hh = 13
        return dt.replace(hour=hh, minute=0, second=0, microsecond=0, tzinfo=_ZONE)
    if "ноч" in s:
        return dt.replace(hour=22, minute=0, second=0, microsecond=0, tzinfo=_ZONE)
    return dt

# ====== Фоллбек-парсер дедлайнов (RU) ======
_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[.\-\/](\d{1,2})(?:[.\-\/](\d{2,4}))?(?!\d)")
WEEKDAYS = {
    "понедельник":0, "понедельнику":0, "в понедельник":0, "к понедельнику":0,
    "вторник":1, "вторнику":1, "во вторник":1, "к вторнику":1,
    "среда":2, "среду":2, "к среде":2, "в среду":2,
    "четверг":3, "к четвергу":3, "в четверг":3,
    "пятница":4, "пятницу":4, "к пятнице":4, "в пятницу":4,
    "суббота":5, "субботу":5, "к субботе":5, "в субботу":5,
    "воскресенье":6, "воскресенью":6, "к воскресенью":6, "в воскресенье":6,
}

def _next_weekday(base: datetime, target_wd: int) -> datetime:
    days_ahead = (target_wd - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)

def _ru_deadline_parse(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    if not text:
        return None
    t = text.lower()
    now = now or datetime.now(_ZONE)

    tm = _TIME_RE.search(t)
    hh, mm = (None, None)
    if tm:
        hh = int(tm.group(1))
        mm = int(tm.group(2))

    slot = None
    if any(w in t for w in ("утр", "утром")): slot = "утро"
    elif any(w in t for w in ("вечер", "вечером")): slot = "вечер"
    elif any(w in t for w in ("обед", "днём", "днем")): slot = "день"
    elif any(w in t for w in ("ноч", "ночью")): slot = "ночь"

    if "послезавтра" in t:
        base = now + timedelta(days=2)
    elif "завтра" in t:
        base = now + timedelta(days=1)
    elif "сегодня" in t:
        base = now
    else:
        base = None

    if base is None:
        m = _DMY_RE.search(t)
        if m:
            d, mth, yr = int(m.group(1)), int(m.group(2)), m.group(3)
            if yr:
                yr = int(yr)
                if yr < 100:
                    yr += 2000
            else:
                yr = now.year
                try:
                    probe = datetime(yr, mth, d, tzinfo=_ZONE)
                    if probe.date() < now.date():
                        yr += 1
                except Exception:
                    pass
            try:
                base = datetime(yr, mth, d, tzinfo=_ZONE)
            except Exception:
                base = None

    if base is None:
        for key, wd in WEEKDAYS.items():
            if key in t:
                base = _next_weekday(now, wd)
                break

    if base is None:
        return None

    if hh is not None and mm is not None:
        dt = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    else:
        if slot == "утро":
            hh_final = max(_START, 9)
            dt = base.replace(hour=hh_final, minute=0, second=0, microsecond=0)
        elif slot == "вечер":
            hh_final = min(_END, 20)
            dt = base.replace(hour=hh_final, minute=0, second=0, microsecond=0)
        elif slot == "день":
            dt = base.replace(hour=13, minute=0, second=0, microsecond=0)
        elif slot == "ночь":
            dt = base.replace(hour=22, minute=0, second=0, microsecond=0)
        else:
            mid = (_START + _END) // 2
            dt = base.replace(hour=mid, minute=0, second=0, microsecond=0)
    return dt

# ====== Форматирование дедлайна ======
def _format_deadline(dt) -> Tuple[Optional[int], Optional[str]]:
    if dt is None:
        return None, None
    if isinstance(dt, (int, float)):
        dt_local = datetime.fromtimestamp(int(dt), tz=_ZONE)
    elif isinstance(dt, datetime):
        dt_local = dt.astimezone(_ZONE)
    else:
        return None, None
    ts = int(dt_local.timestamp())
    s = dt_local.strftime("%Y-%m-%d %H:%M")
    return ts, s

def _choose_greeting() -> str:
    return ["Слышь", "Йо", "Ну чё", "Ало", "Брателло"][hash(os.times()) % 5]

def _safe_username(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    return "@" + s.lstrip("@")

# ====== Основная функция ======
async def assistant_summarize_quick(raw_text: str) -> Dict[str, Any]:
    text = _norm(raw_text)
    if not text:
        return {
            "is_valid": False,
            "violation": "Пустой текст",
            "title": "Миссия",
            "description_og": "",
            "difficulty_points": 1,
            "difficulty_label": _difficulty_label(1),
            "deadline_ts": None,
            "assignee_username": None,
        }

    # 1) Исполнитель из текста
    assignee_from_text = None
    m = ASSIGNEE_RE.search(text)
    if m:
        assignee_from_text = "@" + m.group(1)

    # 2) ИИ-подсказка (если доступна)
    ai_title = "Миссия"
    ai_desc = text
    deadline_hint = None
    assignee_hint = assignee_from_text
    if callable(mission_from_text):
        try:
            ai = await mission_from_text(text)
            if ai:
                ai_title = _norm(ai.get("title")) or ai_title
                ai_desc = text
                deadline_hint = _norm(ai.get("deadline_text"))
                assignee_hint = _safe_username(ai.get("assignee_hint")) or assignee_hint
        except Exception as e:
            logger.warning(f"[assistant] mission_from_text failed: {e}")

    # 3) Дедлайн: внешний парсер → фоллбек → слоты только если нет явного времени
    due_dt: Optional[datetime] = None
    src = deadline_hint or text
    try:
        if callable(nlp_parse):
            due = nlp_parse(src)
            if isinstance(due, (int, float)):
                due_dt = datetime.fromtimestamp(int(due), tz=_ZONE)
            elif isinstance(due, datetime):
                due_dt = due
    except Exception as e:
        logger.warning(f"[assistant] nlp_parse failed: {e}")

    if not isinstance(due_dt, datetime):
        try:
            due_dt = _ru_deadline_parse(src)
        except Exception as e:
            logger.warning(f"[assistant] fallback parse failed: {e}")
            due_dt = None

    if isinstance(due_dt, datetime):
        if not _has_explicit_time(src):
            due_dt = _fix_slot_time(due_dt, src)

    deadline_ts, deadline_str = _format_deadline(due_dt)

    # 4) Сложность/карма
    difficulty = _difficulty_from_text(text)
    label = _difficulty_label(difficulty)
    karma_points = difficulty

    # 5) Итог
    return {
        "is_valid": True,
        "violation": "",
        "title": ai_title,
        "description_og": ai_desc,
        "difficulty_points": difficulty,
        "difficulty_label": label,
        "deadline_ts": deadline_ts,
        "deadline_str": deadline_str,
        "assignee_username": assignee_hint,
        "karma_points": karma_points,
    }

# ====== Рендер «уличного» сообщения ======
def render_street_mission(
    analysis: Dict[str, Any],
    requester_name: Optional[str] = None,
    assignee_name: Optional[str] = None,
) -> str:
    greet = _choose_greeting()
    who = (assignee_name or analysis.get("assignee_username") or "бродяга")
    title = _norm(analysis.get("title")) or "Миссия"
    original = _norm(analysis.get("description_og"))
    diff = int(analysis.get("difficulty_points") or 1)
    label = _difficulty_label(diff)
    karma_points = int(analysis.get("karma_points") or diff)

    deadline_str = analysis.get("deadline_str") or ""
    if not deadline_str and analysis.get("deadline_ts"):
        dt = datetime.fromtimestamp(int(analysis["deadline_ts"]), tz=_ZONE)
        deadline_str = dt.strftime("%Y-%m-%d %H:%M")

    rq = _norm(requester_name) or "Заказчик"
    asg = _norm(assignee_name or analysis.get("assignee_username")) or "Исполнитель"

    lines = [
        f"{greet}, {who}!",
        f"Задача: {title}",
        f"Текст: {original}",
    ]
    if deadline_str:
        lines.append(f"Дедлайн: {deadline_str}")
    lines.extend([
        f"Сложность: {label} ({diff}/5)",
        f"Карма: +{karma_points}",
        f"Заказчик: {rq}",
        f"Исполнитель: {asg}",
        "Давай по-OG — без суеты, но четко. 💪",
    ])
    return "\n".join(lines)

# ====== Совместимость ======
async def classify(text: str) -> Dict[str, Any]:
    return await assistant_summarize_quick(text)

def is_household_task(text: str) -> bool:
    t = _normalize_text(text or "")
    return any(k in t for k in HOUSEHOLD)
