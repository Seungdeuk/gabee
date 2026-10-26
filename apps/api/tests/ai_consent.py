"""테스트용: 가족 그룹의 AI 동의를 켠다(소유자·관리자가 앱에서 켜는 것과 같은 결과)."""

from sqlalchemy import select

from app.features.family_group.models import User
from app.shared import ai_guard
from app.shared.db import SessionLocal


def enable_ai(group_id: str, user_name: str = "지민") -> None:
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.name == user_name)).first()
        ai_guard.set_enabled(db, group_id, user.id, True)


def enable_ai_for_user(user_name: str = "지민") -> None:
    """그 사용자의 활성 가족 그룹에서 AI 동의를 켠다."""
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.name == user_name)).first()
        ai_guard.set_enabled(db, user.active_group_id, user.id, True)
