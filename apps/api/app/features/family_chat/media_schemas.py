from datetime import datetime
from typing import Literal

from pydantic import BaseModel

MediaKind = Literal["image", "file", "video"]


class MediaItem(BaseModel):
    attachment_id: str
    message_id: int
    kind: MediaKind
    user_id: str
    user_name: str
    created_at: datetime
    url: str
    thumb_url: str | None
    width: int | None
    height: int | None
    size_bytes: int | None


class MediaCounts(BaseModel):
    image: int
    file: int
    video: int


class MediaPage(BaseModel):
    items: list[MediaItem]
    next_before_id: int | None
    counts: MediaCounts
