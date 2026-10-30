from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.orm import Session

from app.shared.auth import bearer_user, current_user
from app.shared.db import get_db

from . import service
from .join_router import router as join_router
from .join_schemas import JoinRequestOut
from .models import User
from .photo_router import router as photo_router
from .profile_router import router as profile_router
from .schemas import (
    AccountSignupIn,
    AccountSignupOut,
    CodeIn,
    EmailRequestIn,
    EmailVerifiedOut,
    GroupCreate,
    GroupOut,
    JoinIn,
    LoginIdAvailableOut,
    LoginIn,
    LoginOut,
    PasswordResetCodeConfirmIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RefreshIn,
    SignupOut,
    TesterConsentIn,
    TokenIn,
    TokenOut,
    UserCreate,
    UserOut,
)
from .social_router import router as social_router

router = APIRouter(prefix="/family-group", tags=["family-group"])
router.include_router(join_router)  # 초대·가입 승인(PR 4-B)
router.include_router(social_router)  # Google·Kakao 로그인·연동(PR 4-D)
router.include_router(profile_router)  # 가족 프로필·별명·관리자 지정(PR 4-C)
router.include_router(photo_router)  # 프로필 사진(PR B)


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


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> LoginOut:
    """아이디·비밀번호로 로그인해 Access/Refresh Token 을 받는다."""
    ip = request.client.host if request.client else "unknown"
    return service.login(db, body, ip)


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenOut:
    """Refresh Token 으로 새 Access/Refresh Token 을 받는다(쓴 Refresh Token 은 즉시 폐기)."""
    return service.refresh_session(db, body)


@router.post("/auth/logout", status_code=204)
def logout(body: RefreshIn, db: Session = Depends(get_db)) -> Response:
    """이 세션의 Refresh Token 을 폐기한다. 이미 폐기됐거나 모르는 토큰이어도 204."""
    service.logout(db, body)
    return Response(status_code=204)


@router.post("/auth/email/verify/request", status_code=204)
def email_verify_request(
    user: User = Depends(bearer_user), db: Session = Depends(get_db)
) -> Response:
    """로그인한 사용자에게 인증 메일을 보낸다(재발송 겸용, 이전 링크는 무효)."""
    service.request_email_verification(db, user)
    return Response(status_code=204)


@router.post("/auth/email/verify/confirm", response_model=EmailVerifiedOut)
def email_verify_confirm(body: TokenIn, db: Session = Depends(get_db)) -> EmailVerifiedOut:
    """메일의 토큰으로 이메일 인증을 완료한다(토큰이 자격이라 로그인 없이 부를 수 있다)."""
    return service.confirm_email_verification(db, body)


@router.post("/auth/email/verify/confirm-code", response_model=EmailVerifiedOut)
def email_verify_confirm_code(
    body: CodeIn, user: User = Depends(bearer_user), db: Session = Depends(get_db)
) -> EmailVerifiedOut:
    """메일의 6자리 코드로 이메일 인증을 완료한다(로그인한 본인만. 코드마다 틀릴 수 있는 횟수가 제한된다)."""
    return service.confirm_email_code(db, user, body)


@router.post("/auth/password/reset/request", status_code=204)
def password_reset_request(
    body: PasswordResetRequestIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Response:
    """재설정 메일을 요청한다. 아이디와 이메일이 같은 계정과 둘 다 맞을 때만 보내며, 맞든 아니든 같은 204(발송은 응답 뒤)."""
    ip = request.client.host if request.client else "unknown"
    mail = service.request_password_reset(db, body, ip)
    if mail is not None:
        background.add_task(service.deliver, mail, "password_reset")
    return Response(status_code=204)


@router.post("/auth/login-id/recover", status_code=204)
def login_id_recover(
    body: EmailRequestIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Response:
    """아이디 찾기: 가입한 이메일로 아이디를 보낸다. 계정이 있든 없든 같은 204(발송은 응답 뒤, 아이디는 응답에 싣지 않는다)."""
    ip = request.client.host if request.client else "unknown"
    mail = service.recover_login_id(db, body, ip)
    if mail is not None:
        background.add_task(service.deliver, mail, "login_id_recover")
    return Response(status_code=204)


@router.post("/auth/password/reset/confirm", status_code=204)
def password_reset_confirm(body: PasswordResetConfirmIn, db: Session = Depends(get_db)) -> Response:
    """메일의 토큰과 새 비밀번호로 재설정한다. 모든 기기의 Refresh Token 이 폐기된다."""
    service.confirm_password_reset(db, body)
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserOut)
def auth_me(user: User = Depends(bearer_user)) -> UserOut:
    """Bearer(JWT) 로 인증한 현재 사용자(레거시 토큰은 받지 않는다)."""
    return service.user_out(user)


@router.put("/auth/me/tester-consent", response_model=UserOut)
def put_tester_consent(
    body: TesterConsentIn, user: User = Depends(bearer_user), db: Session = Depends(get_db)
) -> UserOut:
    """테스트 동의서에 동의한 버전과 시각을 저장한다."""
    return service.record_tester_consent(db, user, body.version)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return service.user_out(user)


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(
    body: GroupCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GroupOut:
    return service.create_group(db, user, body.name)


@router.post("/groups/join", response_model=JoinRequestOut)
def join_group(
    body: JoinIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JoinRequestOut:
    """초대 코드로 참여를 신청한다. 가족의 자동 승인이 켜져 있으면 바로 구성원이 되고(status=approved),
    꺼져 있으면 승인 대기 요청(status=pending)이 만들어져 관리자 승인 뒤 구성원이 된다."""
    ip = request.client.host if request.client else "unknown"
    return service.join_group(db, user, body.code, ip)


@router.get("/groups/me", response_model=GroupOut)
def my_group(user: User = Depends(current_user), db: Session = Depends(get_db)) -> GroupOut:
    return service.my_group(db, user)


@router.post("/auth/password/reset/confirm-code", status_code=204)
def password_reset_confirm_code(
    body: PasswordResetCodeConfirmIn, db: Session = Depends(get_db)
) -> Response:
    """메일의 6자리 코드와 아이디, 새 비밀번호로 재설정한다. 틀린 코드·없는 아이디는 같은 응답이다."""
    service.confirm_password_reset_code(db, body)
    return Response(status_code=204)
