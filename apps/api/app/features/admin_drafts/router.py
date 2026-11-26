"""관리자 AI 초안 대기함 API (/admin/service/drafts). 통합관리자만 쓴다.

초안을 만드는 일은 알림 점검 뒤 후속 작업으로도 돈다(아래 register_followup). 초안은 앱에 바로 올라가지 않는다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.alert_rules import register_followup
from app.shared.auth import require_operator
from app.shared.db import get_db
from app.shared.errors import not_found

from . import service
from .schemas import DraftListOut, DraftOut, DraftRunOut, DraftStatusIn, NoticeTopicIn

router = APIRouter(prefix="/admin/service/drafts", tags=["admin-drafts"])
ADMIN = [Depends(require_operator("admin"))]

register_followup("admin_drafts", service.followup)


@router.get("", response_model=DraftListOut, dependencies=ADMIN)
def list_drafts(db: Session = Depends(get_db)) -> DraftListOut:
    """대기 중인 초안과 최근 자동 공지 기록."""
    return service.list_drafts(db)


@router.post("/run", response_model=DraftRunOut, dependencies=ADMIN)
def run_now(db: Session = Depends(get_db)) -> DraftRunOut:
    """지금 한 번 분석한다(알림 점검을 기다리지 않고). 같은 근거로는 초안을 다시 만들지 않는다."""
    return service.run(db)


@router.post("/notice", response_model=DraftOut, dependencies=ADMIN)
def make_notice(body: NoticeTopicIn, db: Session = Depends(get_db)) -> DraftOut:
    """적은 주제(비우면 최근 서버 알림)로 공지 초안을 지금 만든다. 꺼져 있으면 409, 주제·알림 둘 다 없으면 422, AI 실패 503."""
    return service.make_notice(db, body.topic)


@router.post("/reply/{ticket_id}", response_model=DraftOut, dependencies=ADMIN)
def make_reply(ticket_id: str, db: Session = Depends(get_db)) -> DraftOut:
    """문의 하나의 답변 초안을 지금 만든다(가린 제목·내용만 보낸다). 꺼져 있으면 409, 없는 문의 404, AI 실패 503."""
    return service.make_reply(db, ticket_id)


@router.post("/{draft_id}/status", status_code=204, dependencies=ADMIN)
def set_status(draft_id: str, body: DraftStatusIn, db: Session = Depends(get_db)) -> None:
    """초안을 썼음(공지·답변 칸으로 옮김) 또는 버림으로 바꾼다. 없는 번호면 404."""
    if not service.set_status(db, draft_id, body.status):
        raise not_found("초안")
