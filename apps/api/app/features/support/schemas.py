from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["inquiry", "report"]
Status = Literal["new", "working", "done"]


class TicketIn(BaseModel):
    kind: Kind
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=2000)


class TicketOut(BaseModel):
    """보낸 사람 본인에게 보여 주는 모양."""

    id: str
    kind: Kind
    title: str
    body: str
    status: Status
    answer: str | None
    answered_at: datetime | None
    created_at: datetime


class TicketList(BaseModel):
    rows: list[TicketOut]
