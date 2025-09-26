from __future__ import annotations
import os, json, random
from typing import List, Optional

BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "gifs")
CATS = {"task_create","on_time","early","late","rank_up","achieve"}

def _path(cat: str) -> str:
    os.makedirs(BASE, exist_ok=True)
    return os.path.join(BASE, f"{cat}.json")

async def pick_gif(cat: str) -> Optional[str]:
    if cat not in CATS: return None
    p = _path(cat)
    if not os.path.exists(p): return None
    try:
        data: List[str] = json.load(open(p, "r", encoding="utf-8"))
        return random.choice(data) if data else None
    except Exception:
        return None

async def remember_gif(cat: str, file_id: str) -> bool:
    if cat not in CATS: return False
    p = _path(cat)
    data: List[str] = []
    if os.path.exists(p):
        try:
            data = json.load(open(p, "r", encoding="utf-8"))
        except Exception:
            data = []
    if file_id not in data:
        data.append(file_id)
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return True
