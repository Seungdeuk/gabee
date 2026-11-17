"""통합관리자 챗봇 API. `require_operator("admin")` 를 거친다. 가족 데이터는 다루지 않는다."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import require_operator
from app.shared.db import get_db

from . import service
from .schemas import AdminAskEvent, AdminAskIn, AdminAskOut

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])


@router.post("/ask", response_model=AdminAskOut)
def ask(
    body: AdminAskIn,
    user: User = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> AdminAskOut:
    """챗봇 질문을 지금 숫자와 함께 Claude 에게 보낸다."""
    return service.ask(db, user.id, body.q)


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "model": AdminAskEvent,
            "description": "text/event-stream. `data: ` 줄마다 AdminAskEvent 하나(JSON). 마지막은 answer 또는 error",
        }
    },
)
def ask_stream(
    body: AdminAskIn,
    user: User = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """/ask 와 같은 답을 단계 소식과 함께 보낸다(SSE). DB 연결은 스트림이 끝난 뒤 닫힌다."""
    events = service.ask_stream(db, user.id, body.q)
    return StreamingResponse(
        (f"data: {e.model_dump_json(exclude_none=True)}\n\n" for e in events),
        media_type="text/event-stream",
        # 중간 서버(프록시)가 모았다가 한꺼번에 보내지 않게 한다
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
