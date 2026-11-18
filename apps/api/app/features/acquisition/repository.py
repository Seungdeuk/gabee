"""install_sources 접근. 업무 규칙(언제 저장하나)은 service.py 에 있고 여기서는 DB 만 다룬다."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import InstallSource


def insert_if_absent(db: Session, row: InstallSource) -> bool:
    """그 사람의 줄이 아직 없을 때만 넣는다. 넣었으면 True, 이미 있으면 False(처음 값을 그대로 둔다).
    같은 사람이 동시에 두 번 보내도 기본키 때문에 한 줄만 남는다."""
    if db.get(InstallSource, row.user_id) is not None:
        return False
    try:
        with db.begin_nested():
            db.add(row)
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
