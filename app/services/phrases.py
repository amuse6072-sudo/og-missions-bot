from __future__ import annotations
import json, os, random
from typing import Dict, List

BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "phrases")

CATEGORIES = {
    "task_create": "task_create.json",
    "on_time": "on_time.json",
    "early": "early.json",
    "late": "late.json",
    "achieve": "achieve.json",
    "rank_up": "rank_up.json"
}

_cache: Dict[str, List[str]] = {}

def load_category(cat: str) -> List[str]:
    if cat in _cache:
        return _cache[cat]
    fname = CATEGORIES.get(cat)
    if not fname:
        return []
    path = os.path.join(BASE, fname)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        _cache[cat] = json.load(f)
    return _cache[cat]

def line(cat: str) -> str:
    lines = load_category(cat)
    return random.choice(lines) if lines else ""
