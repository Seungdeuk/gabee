"""유입 경로 저장. 로그인한 본인 것만 저장하고 가족이 없어도 된다 — docs/requirements/acquisition.md."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .schemas import InstallSourceIn

router = APIRouter(prefix="/acquisition", tags=["acquisition"])


@router.post("/install-source", status_code=204)
def save_install_source(
    body: InstallSourceIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    """앱이 읽은 설치 꼬리표(utm 세 값)를 한 번 저장한다. 이미 있거나 가입 30일이 지났으면 아무것도 바꾸지 않는다."""
    service.save(db, user, body)
