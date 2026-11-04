"""요청자 신원.

- 정식 회원(아이디/비밀번호 가입): 로그인으로 받은 Access Token(JWT) 을 `Authorization: Bearer` 로 보낸다.
- 익명 계정(개발·전환기): 가입하면 받는 `X-Gyeot-Token`(원본 프로젝트와 같은 방식). `ALLOW_LEGACY_TOKEN_AUTH=false` 로 끈다.
둘은 섞이지 않는다: Bearer 가 있으면 Bearer 만, 정식 회원은 레거시 토큰을 쓸 수 없다.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .config import settings
from .db import get_db
from .errors import ApiError, bad_request
from .tokens import TokenError, password_version, verify_access_token


def _bearer_token(authorization: str) -> str:
    """`Authorization: Bearer <token>` 에서 토큰만 꺼낸다. 형식이 다르면 401."""
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ApiError(401, "token_invalid", "Authorization 헤더는 'Bearer <토큰>' 형식이어야 해요")
    return parts[1]


def _user_from_bearer(authorization: str, db: Session) -> User:
    try:
        user_id, pv = verify_access_token(_bearer_token(authorization))
    except TokenError as exc:
        if exc.expired:
            raise ApiError(
                401, "token_expired", "로그인이 만료됐어요. 다시 로그인해 주세요"
            ) from exc
        raise ApiError(401, "token_invalid", "토큰이 올바르지 않아요") from exc
    # 권한 판단에 쓰는 값(role, 그룹)은 토큰 클레임이 아니라 요청마다 DB 에서 읽는다.
    # 계정이 삭제됐으면 토큰이 유효해도 거부한다(users 에는 비활성 컬럼이 아직 없다).
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(401, "token_invalid", "토큰이 올바르지 않아요")
    if pv != password_version(user.password_hash):
        # 토큰 발급 뒤 비밀번호가 바뀌었다(재설정 등) — 이전 Access Token 은 즉시 무효. 클라이언트는 다시 로그인한다.
        raise ApiError(401, "token_invalid", "비밀번호가 바뀌어 다시 로그인해야 해요")
    return user


def bearer_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    """Bearer(JWT) 로만 인증한다(레거시 토큰 불가). 정식 회원 전용 엔드포인트용."""
    if authorization is None:
        raise ApiError(401, "token_required", "로그인이 필요해요")
    return _user_from_bearer(authorization, db)


def _require_tester_consent(user: User) -> None:
    """테스트 참여 동의를 요구하는 설정이면 동의 버전이 다른 정식 회원을 403 으로 막는다.
    `current_user` 와 `require_operator` 가 같은 조건을 쓰도록 한 곳에 둔다."""
    if (
        settings.require_tester_consent
        and user.tester_consent_version != settings.tester_consent_version
    ):
        # /auth/me 와 동의 저장(bearer_user)은 막지 않아서 앱이 동의 화면을 띄우고 동의를 저장할 수 있다
        raise ApiError(403, "tester_consent_required", "테스트 참여 동의서에 먼저 동의해 주세요")


def current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_gyeot_token: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    """Authorization 헤더가 있으면 반드시 Bearer(JWT) 로 인증한다 — 검증에 실패해도 X-Gyeot-Token 으로
    넘어가지 않는다(우회 방지). 없을 때만 레거시 X-Gyeot-Token 을 본다."""
    if authorization is not None:
        user = _user_from_bearer(authorization, db)
        _require_tester_consent(user)
        return user
    if not x_gyeot_token:
        raise ApiError(401, "token_required", "먼저 가입하거나 로그인해 주세요")
    if not settings.allow_legacy_token_auth:
        raise ApiError(401, "legacy_auth_disabled", "이 서버는 로그인(Bearer 토큰)이 필요해요")
    user = db.scalar(select(User).where(User.token == x_gyeot_token))
    if user is None:
        raise ApiError(401, "token_invalid", "토큰이 올바르지 않아요")
    if user.login_id is not None or user.password_hash is not None:
        # 아이디/비밀번호로 가입한 정식 회원은 레거시 고정 토큰으로 들어올 수 없다(레거시 인증은 익명 계정 전용).
        # 존재 여부를 알려주지 않으려 같은 응답을 쓴다.
        raise ApiError(401, "token_invalid", "토큰이 올바르지 않아요")
    return user


# 운영자 scope → 허용 목록 설정 이름. 두 scope 는 서로를 포함하지 않는다(한 사람이 둘 다 맡으면 두 목록에 같은 id 를 둔다).
OPERATOR_SCOPES: dict[str, str] = {
    "ops_admin": "ops_admin_user_ids",  # 운영 관리자 페이지(서버·시스템 상태)
    "service_admin": "service_admin_user_ids",  # 서비스 관리자 페이지(사용자 이용·서비스 상태)
}


def parse_user_id_list(raw: str) -> frozenset[str]:
    """쉼표로 구분한 사용자 id 목록을 집합으로 바꾼다. 앞뒤 공백은 지우고 빈 항목은 무시한다.
    비교는 정확히 일치할 때만 통과하므로 부분 일치·대소문자 무시는 하지 않는다."""
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def require_operator(scope: str) -> Callable[..., User]:
    """서비스 운영자만 통과시키는 의존성을 만든다. 예: `Depends(require_operator("ops_admin"))`.

    판단 기준은 가족 역할(group_members.role)이 아니라 scope 별 허용 목록(환경변수)의 사용자 id 뿐이다.
    순서: Bearer(JWT) 인증 → 허용 목록 → 테스트 참여 동의. 인증된 비운영자는 동의 여부와 상관없이 항상 같은 403
    `operator_required` 이고(토큰이 없거나 만료·무효이면 그 전에 401), 허용 목록의 내용·크기는 응답에 드러내지 않는다. 목록은 요청마다 settings 에서 읽고,
    비어 있거나 설정이 없으면 아무도 허용하지 않는다. 알 수 없는 scope 는 의존성을 만들 때 ValueError 로 알린다.
    """
    field = OPERATOR_SCOPES.get(scope)
    if field is None:
        raise ValueError(f"알 수 없는 운영자 scope: {scope!r} (가능: {', '.join(OPERATOR_SCOPES)})")

    def dependency(user: User = Depends(bearer_user)) -> User:
        if user.id not in parse_user_id_list(getattr(settings, field)):
            raise ApiError(403, "operator_required", "운영자 권한이 필요해요")
        _require_tester_consent(user)
        return user

    return dependency


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
