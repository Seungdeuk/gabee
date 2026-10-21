from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .models import User
from .schemas import GroupCreate, GroupOut, JoinIn, SignupOut, UserCreate, UserOut

router = APIRouter(prefix="/family-group", tags=["family-group"])


@router.post("/users", response_model=SignupOut, status_code=201)
def signup(body: UserCreate, db: Session = Depends(get_db)) -> SignupOut:
    """이름·역할로 가입하고 토큰을 받는다(토큰 없이 부를 수 있는 유일한 경로)."""
    return service.signup(db, body)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return service.user_out(user)


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(
    body: GroupCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GroupOut:
    return service.create_group(db, user, body.name)


@router.post("/groups/join", response_model=GroupOut)
def join_group(
    body: JoinIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GroupOut:
    return service.join_group(db, user, body.code)


@router.get("/groups/me", response_model=GroupOut)
def my_group(user: User = Depends(current_user), db: Session = Depends(get_db)) -> GroupOut:
    return service.my_group(db, user)
