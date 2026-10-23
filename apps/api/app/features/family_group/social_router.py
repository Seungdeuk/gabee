"""Google·Kakao 로그인과 계정 연동(PR 4-D) 엔드포인트. family_group 라우터에 포함되어 /family-group 아래로 열린다."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.shared.auth import bearer_user
from app.shared.db import get_db

from . import social_service
from .models import User
from .schemas import LoginOut
from .social_schemas import (
    Provider,
    SocialAccountOut,
    SocialCandidateOut,
    SocialLinkIn,
    SocialLoginIn,
)

router = APIRouter()


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/social/{provider}", response_model=LoginOut | SocialCandidateOut)
def social_login(
    provider: Provider, body: SocialLoginIn, request: Request, db: Session = Depends(get_db)
) -> LoginOut | SocialCandidateOut:
    """Google(ID 토큰)·Kakao(액세스 토큰)로 로그인하거나 처음이면 가입한다. 같은 이메일의 기존 계정이 있으면 자동으로 합치지 않고
    `{candidate_account: true, masked_email}` 만 돌려준다(기존 방식으로 로그인한 뒤 연동)."""
    return social_service.login(db, provider, body, _ip(request))


@router.get("/auth/social", response_model=list[SocialAccountOut])
def linked_accounts(
    user: User = Depends(bearer_user), db: Session = Depends(get_db)
) -> list[SocialAccountOut]:
    """내 계정에 연결된 소셜 계정 목록."""
    return [
        SocialAccountOut(provider=a.provider, linked_at=a.linked_at)
        for a in social_service.linked(db, user)
    ]


@router.post("/auth/social/{provider}/link", status_code=204)
def link_account(
    provider: Provider,
    body: SocialLinkIn,
    request: Request,
    user: User = Depends(bearer_user),
    db: Session = Depends(get_db),
) -> Response:
    """로그인한 내 계정에 소셜 계정을 연결한다. 비밀번호가 있는 계정은 비밀번호를 한 번 더 확인한다."""
    social_service.link(db, user, provider, body, _ip(request))
    return Response(status_code=204)


@router.delete("/auth/social/{provider}", status_code=204)
def unlink_account(
    provider: Provider, user: User = Depends(bearer_user), db: Session = Depends(get_db)
) -> Response:
    """소셜 연동을 해제한다. 로그인 수단이 하나도 남지 않게 되면 403 last_login_method."""
    social_service.unlink(db, user, provider)
    return Response(status_code=204)
