"""요청자 신원. 로그인 없이 이름·역할로 가입하면 토큰을 받고, 이후 `X-Gyeot-Token` 헤더로 보낸다(원본 프로젝트와 같은 방식).

TODO: 소셜 로그인(Firebase 등)을 붙일 때 이 파일의 `current_user`만 바꾸면 된다.
"""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .db import get_db
from .errors import ApiError, bad_request


def current_user(
    x_gyeot_token: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    if not x_gyeot_token:
        raise ApiError(401, "token_required", "먼저 가입하거나 로그인해 주세요")
    user = db.scalar(select(User).where(User.token == x_gyeot_token))
    if user is None:
        raise ApiError(401, "token_invalid", "토큰이 올바르지 않아요")
    return user


def ensure_group_member(db: Session, user_id: str, group_id: str) -> None:
    """user_id 가 group_id 의 실제 구성원인지 group_members 로 확인한다(캐시값인
    active_group_id 를 그대로 믿지 않는다). FastAPI 에 묶여 있지 않으므로 라우터를
    거치지 않고 Service 를 직접 호출하는 코드(예: 향후 AI Agent)도 그 전에 반드시
    이 함수를 호출해야 한다 — docs/contracts/permissions.md 참고."""
    if db.get(GroupMember, (group_id, user_id)) is None:
        raise ApiError(403, "not_member", "이 그룹의 구성원이 아니에요")


def current_group_id(user: User = Depends(current_user), db: Session = Depends(get_db)) -> str:
    """가족 그룹이 있어야 쓸 수 있는 기능(소통, 일정, 가계, 돌봄)의 그룹 id.
    active_group_id 가 설정돼 있어도 group_members 기준 실제 구성원인지 함께 확인한다."""
    if not user.active_group_id:
        raise bad_request("no_group", "가족 그룹에 먼저 참여해 주세요")
    ensure_group_member(db, user.id, user.active_group_id)
    return user.active_group_id
