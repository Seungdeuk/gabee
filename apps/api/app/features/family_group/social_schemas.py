"""Google·Kakao 로그인과 계정 연동(PR 4-D)의 요청·응답 모델."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Provider = Literal["google", "kakao"]


class SocialLoginIn(BaseModel):
    """provider_token: Google=ID 토큰(JWT), Kakao=액세스 토큰. 처음 가입할 때만 role 을 쓴다."""

    provider_token: str = Field(min_length=10, max_length=4096)
    role: Literal["parent", "child", "other"] = "child"
    device_label: str | None = Field(default=None, max_length=60)


class SocialLinkIn(BaseModel):
    """이미 로그인한 계정에 소셜 계정을 연결한다. 비밀번호가 있는 계정은 비밀번호를 다시 확인한다."""

    provider_token: str = Field(min_length=10, max_length=4096)
    password: str | None = Field(default=None, max_length=256)


class SocialCandidateOut(BaseModel):
    """같은 이메일의 기존 계정이 있다 — 자동으로 합치지 않는다. 기존 방식으로 로그인한 뒤 연동해야 한다."""

    candidate_account: bool = True
    masked_email: str


class SocialAccountOut(BaseModel):
    provider: str
    linked_at: datetime
