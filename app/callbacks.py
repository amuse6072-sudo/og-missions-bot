from __future__ import annotations

from typing import Optional

from aiogram.filters.callback_data import CallbackData


class MenuCb(CallbackData, prefix="menu"):
    action: str  # "missions" | "my" | "stats" | "help" | "admin"


class MissionCb(CallbackData, prefix="msn"):
    action: str  # "open" | "accept" | "done" | "fail" | "details" | "assign" | "edit" | "delete" | "back"
    mid: int
    page: Optional[int] = None


class PagerCb(CallbackData, prefix="pg"):
    page: int
    total: int
    scope: str
    payload: Optional[str] = None  # произвольный идентификатор контекста


class StepperCb(CallbackData, prefix="stp"):
    action: str  # "prev" | "next" | "save" | "cancel"
    sid: str     # идентификатор шага/сессии
    step: int


class AdminCb(CallbackData, prefix="adm"):
    action: str  # "promote" | "demote" | "wipe" | "stats" | "broadcast" | "back"
    uid: Optional[int] = None
