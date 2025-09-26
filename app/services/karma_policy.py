from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple
import re

"""
Прозрачные правила кармы и сложности.
— Категория определяется по ключам.
— Сложность 1..5, награда = сложность + бонус за срочность (если дедлайн сегодня).
— Штрафы: отказ, перенос (1/2/3 дня), доработка.
Все числа легко настраиваемы.
"""

__all__ = [
    "KarmaDecision",
    "estimate",
    "decline_penalty",
    "postpone_penalty",
    "rework_penalty",
    "CATEGORY_KEYWORDS",
    "CATEGORY_BASE_DIFFICULTY",
    "score_task",
]

# Ключевые слова по категориям
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "housekeeping": ["мусор", "убор", "убрать", "помыть", "курьер", "донести", "перенести", "закупить"],
    "record":       ["запис", "вокал", "куплет", "дубл", "голос", "битовая", "флоу"],
    "mix":          ["свести", "микс", "эквал", "eq", "компресс", "master", "мастер", "мастеринг"],
    "video":        ["монтаж", "видео", "склей", "цветкор", "color", "титры", "саб", "субтитр"],
    "design":       ["обложка", "логотип", "баннер", "постер", "рендер", "нейрон", "промпт", "макет", "вектор"],
    "smm":          ["пост", "instagram", "инстаграм", "тизер", "снипет", "snippet", "shorts", "сторис"],
    "dev":          ["бот", "скрипт", "код", "python", "py", "api", "интеграция", "pipeline"],
    # добавляй свои домены тут
}

# Базовая сложность по категориям (1..5)
CATEGORY_BASE_DIFFICULTY: Dict[str, int] = {
    "housekeeping": 1,
    "smm":          2,
    "design":       3,
    "record":       3,
    "video":        4,
    "dev":          4,
    "mix":          5,
}

# Бонус и штрафы
URGENCY_BONUS_TODAY = 1
DECLINE_PENALTY = -3
POSTPONE_PENALTIES = {1: 0, 2: -1, 3: -2}
REWORK_PENALTY = -1

@dataclass
class KarmaDecision:
    category: str
    difficulty: int         # 1..5
    base_points: int        # обычно = difficulty
    urgency_bonus: int      # 0/1
    total_reward: int       # base_points + urgency_bonus

def _match_category(text: str) -> str:
    s = text.lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", s) for w in words):
            return cat
    return "housekeeping"

def estimate(text: str, *, due_today: bool = False) -> KarmaDecision:
    cat = _match_category(text)
    diff = int(max(1, min(5, CATEGORY_BASE_DIFFICULTY.get(cat, 2))))
    # лёгкая надбавка за объём текста
    if len(text) > 80:
        diff = min(5, diff + 1)
    base = diff
    bonus = URGENCY_BONUS_TODAY if due_today else 0
    return KarmaDecision(
        category=cat,
        difficulty=diff,
        base_points=base,
        urgency_bonus=bonus,
        total_reward=base + bonus,
    )

def decline_penalty() -> int:
    return DECLINE_PENALTY

def postpone_penalty(days: int) -> int:
    return POSTPONE_PENALTIES.get(int(days), -2)

def rework_penalty() -> int:
    return REWORK_PENALTY

def score_task(text: str, due_today: bool) -> Tuple[int, str]:
    """
    Удобный шорткат: вернуть (очки, ярлык) по тексту.
    """
    dec = estimate(text, due_today=due_today)
    labels = {1:"🟢 Лёгкая", 2:"🟡 Средняя", 3:"🟠 Выше средней", 4:"🔴 Тяжёлая", 5:"🟣 Хардкор"}
    return dec.total_reward, labels.get(dec.difficulty, "🟡 Средняя")
