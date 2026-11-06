from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Category = Literal["update", "info", "maintenance"]


class NoticeOut(BaseModel):
    """앱 사용자에게 보여 주는 모양. 쓴 관리자는 담지 않는다."""

    id: str
    category: Category
    title: str
    body: str
    created_at: datetime
    updated_at: datetime


class NoticeList(BaseModel):
    rows: list[NoticeOut]
