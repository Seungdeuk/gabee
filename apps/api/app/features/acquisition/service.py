"""유입 경로 저장 규칙: 한 사람당 처음 한 번만, 가입한 지 얼마 안 된 사람만 저장한다."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group.models import User

from . import repository
from .models import InstallSource
from .schemas import InstallSourceIn

# 가입한 지 이보다 오래된 회원은 저장하지 않는다. 오래된 회원이 앱을 다시 설치했을 때
# "그 링크로 가입했다"고 잘못 세지 않기 위해서다(docs/requirements/acquisition.md 미정 4).
NEW_MEMBER_WINDOW = timedelta(days=30)


def _aware(at: datetime) -> datetime:
    """SQLite 는 시간대 없는 값을 돌려준다(UTC 로 저장했다)."""
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at


def save(db: Session, user: User, body: InstallSourceIn, now: datetime | None = None) -> bool:
    """저장했으면 True. 이미 있거나 오래된 회원이면 False(응답은 똑같이 204 라 앱은 구분하지 않는다)."""
    now = now or datetime.now(UTC)
    if now - _aware(user.created_at) > NEW_MEMBER_WINDOW:
        return False
    row = InstallSource(
        user_id=user.id,
        source=body.source,
        medium=body.medium,
        campaign=body.campaign,
        created_at=now,
    )
    return repository.insert_if_absent(db, row)
