from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field

StatusT = Literal["open", "in_progress", "done", "failed"]


class Mission(BaseModel):
    id: Optional[int] = None
    title: str
    description: str = ""
    status: StatusT = "open"
    creator_id: int
    assignee_id: Optional[int] = None
    karma: int = 0
    created_at: int = Field(default_factory=lambda: 0)
    due_at: Optional[int] = None

    class Config:
        extra = "ignore"
