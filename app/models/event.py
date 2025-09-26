from __future__ import annotations
from typing import Optional, Dict, Any
from pydantic import BaseModel


class Event(BaseModel):
    id: Optional[int] = None
    type: str
    payload: Dict[str, Any] = {}
    created_at: int = 0

    class Config:
        extra = "ignore"
