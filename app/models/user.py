from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class User(BaseModel):
    id: Optional[int] = None
    tg_id: int
    username: Optional[str] = None
    full_name: Optional[str] = None
    rank: str = "rookie"
    karma: int = 0

    class Config:
        extra = "ignore"
