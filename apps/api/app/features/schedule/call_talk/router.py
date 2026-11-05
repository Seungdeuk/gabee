"""전화 이야깃거리 API. `check_router.py` 에서 `/schedule/check/members/{user_id}/call-talk` 로 붙는다.

로그인과 현재 가족 그룹이 필요하다. 대상이 같은 그룹 구성원이 아니면 404, 그 밖에는 항상 200 이다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .schemas import CallTalkOut

router = APIRouter()


@router.post("/members/{user_id}/call-talk", response_model=CallTalkOut)
def call_talk(
    user_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    """가비가 추천하는 이야깃거리. source ai 면 문구 한 쌍, greeting 이면 안부 문구(reason 이 이유)."""
    return service.call_talk(db, user.id, group_id, user_id)
