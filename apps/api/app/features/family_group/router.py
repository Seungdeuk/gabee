from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .models import User
from .schemas import (
    AccountSignupIn,
    AccountSignupOut,
    GroupCreate,
    GroupOut,
    JoinIn,
    LoginIdAvailableOut,
    SignupOut,
    UserCreate,
    UserOut,
)

router = APIRouter(prefix="/family-group", tags=["family-group"])


@router.post("/users", response_model=SignupOut, status_code=201)
def signup(body: UserCreate, db: Session = Depends(get_db)) -> SignupOut:
    """이름·역할로 가입하고 토큰을 받는다(토큰 없이 부를 수 있는 유일한 경로)."""
    return service.signup(db, body)


@router.post("/auth/signup", response_model=AccountSignupOut, status_code=201)
def signup_account(body: AccountSignupIn, db: Session = Depends(get_db)) -> AccountSignupOut:
    """아이디·비밀번호·이메일로 회원가입한다(토큰 없이 부를 수 있다). 로그인은 별도 단계."""
    return service.signup_account(db, body)


@router.get("/auth/login-id-available", response_model=LoginIdAvailableOut)
def login_id_available(login_id: str, db: Session = Depends(get_db)) -> LoginIdAvailableOut:
    """가입 화면의 아이디 중복 확인."""
    return service.login_id_available(db, login_id)


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
