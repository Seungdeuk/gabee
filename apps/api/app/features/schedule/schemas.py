from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    starts_at: datetime
    note: str = ""
    status: Literal["pending", "confirmed"] = "confirmed"
    source: Literal["manual", "chat", "photo"] = "manual"


class EventOut(BaseModel):
    id: str
    title: str
    starts_at: datetime
    note: str
    status: str
    source: str
    created_by: str
