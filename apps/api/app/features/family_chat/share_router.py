"""공유 카드 엔드포인트. family_chat 라우터에 포함되어 /family-chat/shares 로 열린다. AI 를 부르지 않는다.
카드 테이블(message_shares)이 준비되지 않은 DB 면 이 API 만 503(chat_share)이고 소통의 나머지는 그대로다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db
from app.shared.schema_gate import schema_ready

from . import share_service
from .schemas import MessageOut, ShareCreate

router = APIRouter(prefix="/shares", dependencies=[Depends(schema_ready("chat_share"))])


@router.post("", response_model=MessageOut, status_code=201)
def send_share(
    body: ShareCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    """내 일정 한 건 또는 그 달 내 정산 몫을 카드로 방에 올린다. 내용은 서버가 읽어 보낸 시점 그대로 저장하고,
    내가 포함된 것이 아니면 404, 상대가 나간 1:1 방이면 409, 너무 자주 보내면 429 다."""
    return share_service.send(db, user, group_id, body)
