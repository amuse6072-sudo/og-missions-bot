from __future__ import annotations
from dataclasses import dataclass

__all__ = [
    "MissionBrief",
    "line_created",
    "line_sent_to_assignee",
    "line_assignee_prompt",
    "line_accepted",
    "line_declined",
    "line_postponed",
    "line_done",
    "line_rework",
    "line_deleted_penalty",
    "line_deleted_no_penalty",
]

# ───────────────────────── Helpers ─────────────────────────

def _safe_str(v: object, default: str = "—") -> str:
    s = "" if v is None else str(v).strip()
    return s if s else default

def _safe_int(v: object, default: int = 0) -> int:
    try:
        return int(v)  # может быть bool, str, None
    except Exception:
        return default

def _fmt_name(name: str | None) -> str:
    return _safe_str(name)

def _fmt_deadline(deadline_str: str | None) -> str:
    # ожидаем уже отформатированную строку вида "12.09 20:00"
    return _safe_str(deadline_str)

def _fmt_points(points: int | None) -> int:
    return abs(_safe_int(points, 0))

def _fmt_penalty(points: int | None) -> int:
    return abs(_safe_int(points, 0))

def _plural_days_ru(n: int) -> str:
    # 1 день, 2/3/4 дня, 5+ дней
    n = abs(int(n))
    if 11 <= (n % 100) <= 14:
        return "дней"
    tail = n % 10
    if tail == 1:
        return "день"
    if 2 <= tail <= 4:
        return "дня"
    return "дней"

# ───────────────────────── Data ─────────────────────────

@dataclass
class MissionBrief:
    title: str
    description: str
    assignee_name: str          # отображаемое имя/ник исполнителя
    deadline_str: str           # уже отформатированный дедлайн, напр. "12.09 20:00"
    reward_points: int          # сколько кармы за выполненную
    difficulty: int             # 1..5

# ── Создание / рассылка ───────────────────────────────────────────────

def line_created(brief: MissionBrief) -> str:
    title = _safe_str(brief.title)
    desc = _safe_str(brief.description)
    who = _fmt_name(brief.assignee_name)
    deadline = _fmt_deadline(brief.deadline_str)
    reward = _fmt_points(brief.reward_points)
    diff = _safe_int(brief.difficulty, 1)

    return (
        f"🏁 Миссия собрана: {title}\n"
        f"{desc}\n"
        f"👤 Исполнитель: {who}\n"
        f"⏰ Дедлайн: {deadline}\n"
        f"🏅 Награда: +{reward} (сложн. {diff}/5)\n\n"
        f"Двигаем по-OG: отправляю на подтверждение исполнителю."
    )

def line_sent_to_assignee(brief: MissionBrief) -> str:
    who = _fmt_name(brief.assignee_name)
    deadline = _fmt_deadline(brief.deadline_str)
    reward = _fmt_points(brief.reward_points)
    desc = _safe_str(brief.description)

    return (
        f"📨 Миссия ушла на рассмотрение: {who}\n"
        f"⏰ Дедлайн: {deadline} · 🏅 Награда: +{reward}\n"
        f"📝 Кратко: {desc}"
    )

def line_assignee_prompt(brief: MissionBrief) -> str:
    who = _fmt_name(brief.assignee_name)
    title = _safe_str(brief.title)
    desc = _safe_str(brief.description)
    deadline = _fmt_deadline(brief.deadline_str)
    reward = _fmt_points(brief.reward_points)
    diff = _safe_int(brief.difficulty, 1)

    return (
        f"Йо, {who}! Квест: {title}\n"
        f"{desc}\n"
        f"⏰ Дедлайн: {deadline}\n"
        f"🏅 За сдачу: +{reward} (сложн. {diff}/5)\n\n"
        f"Жмёшь: ✅ Принять · ❌ Отказаться · ⏳ Перенести"
    )

# ── Ответ исполнителя ────────────────────────────────────────────────

def line_accepted(user_name: str) -> str:
    who = _fmt_name(user_name)
    return f"✅ {who} в деле. Погнали."

def line_declined(user_name: str, penalty: int) -> str:
    who = _fmt_name(user_name)
    pen = _fmt_penalty(penalty)
    tail = f" (−{pen} кармы)" if pen else ""
    return f"❌ {who} отказывается{tail}. Берём другого."

def line_postponed(user_name: str, days: int, penalty: int) -> str:
    who = _fmt_name(user_name)
    d = _safe_int(days, 1)
    pen = _fmt_penalty(penalty)
    day_word = _plural_days_ru(d)
    tail = f" (−{pen} кармы)" if pen else ""
    return f"⏳ {who} перенёс на {d} {day_word}.{tail}"

# ── Ревью / финал ────────────────────────────────────────────────────

def line_done(user_name: str, points: int) -> str:
    who = _fmt_name(user_name)
    pts = _fmt_points(points)
    return f"🏆 {who} закрыл миссию. +{pts} к карме. Респект."

def line_rework(user_name: str, penalty: int) -> str:
    who = _fmt_name(user_name)
    pen = _fmt_penalty(penalty)
    tail = f" −{pen} к карме" if pen else ""
    return f"🔁 {who}, на доработку.{tail} Подтягивай детали и возвращай."

# ── Админские события ────────────────────────────────────────────────

def line_deleted_penalty(mission_id: int, user_name: str | None, penalty: int) -> str:
    who = f" для {_fmt_name(user_name)}" if user_name else ""
    pen = _fmt_penalty(penalty)
    tail = f" −{pen} к карме" if pen else ""
    mid = _safe_int(mission_id, 0)
    return f"🗑 Миссия #{mid} удалена админом{who}.{tail}"

def line_deleted_no_penalty(mission_id: int) -> str:
    mid = _safe_int(mission_id, 0)
    return f"♻️ Миссия #{mid} удалена админом без штрафа."
