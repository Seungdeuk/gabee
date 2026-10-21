"""요청자 신원. 로그인 없이 이름·역할로 가입하면 토큰을 받고, 이후 `X-Gyeot-Token` 헤더로 보낸다(원본 프로젝트와 같은 방식).

TODO: 소셜 로그인(Firebase 등)을 붙일 때 이 파일의 `current_user`만 바꾸면 된다.
"""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_group.models import User

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


def current_group_id(user: User = Depends(current_user)) -> str:
    """가족 그룹이 있어야 쓸 수 있는 기능(소통, 일정, 가계, 돌봄)의 그룹 id."""
    if not user.active_group_id:
        raise bad_request("no_group", "가족 그룹에 먼저 참여해 주세요")
    return user.active_group_id
