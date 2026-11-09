"""통합관리자 챗봇 API. `require_operator("admin")` 를 거친다. 가족 데이터는 다루지 않는다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import require_operator
from app.shared.db import get_db

from . import service
from .schemas import AdminAskIn, AdminAskOut

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])


@router.post("/ask", response_model=AdminAskOut)
def ask(
    body: AdminAskIn,
    user: User = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> AdminAskOut:
    """챗봇 질문을 지금 숫자와 함께 Claude 에게 보낸다."""
    return service.ask(db, user.id, body.q)
