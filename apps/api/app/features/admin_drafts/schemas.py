from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DraftKind = Literal["notice", "reply"]
NoticeCategory = Literal["update", "info", "maintenance"]


class DraftOut(BaseModel):
    id: str
    kind: DraftKind
    ticket_id: str | None  # 답변 초안이면 원래 문의 번호
    category: NoticeCategory | None
    title: str | None
    body: str
    reason: str  # 왜 이 초안을 만들었나
    status: Literal["pending", "used", "dismissed"]
    auto: bool  # 자동 공지로 이미 올렸나
    notice_id: str | None
    created_at: datetime


class DraftListOut(BaseModel):
    enabled: bool  # ADMIN_DRAFTS_ENABLED
    auto_notice_enabled: bool  # AUTO_NOTICE_ENABLED
    pending: list[DraftOut]  # 대기 중인 초안(최근순)
    auto_notices: list[DraftOut]  # 최근 자동 공지 기록(최대 5개)


class DraftRunOut(BaseModel):
    enabled: bool
    notices: int  # 새로 만든 공지 초안 수
    replies: int  # 새로 만든 답변 초안 수
    published: int  # 자동으로 올린 공지 수


class NoticeTopicIn(BaseModel):
    topic: str = Field(default="", max_length=300)  # 어떤 공지를 쓸지(비우면 최근 서버 알림으로)


class DraftStatusIn(BaseModel):
    status: Literal["used", "dismissed"]  # 썼음(공지·답변 칸으로 옮김) | 버림
