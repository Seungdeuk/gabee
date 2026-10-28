from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: Literal["parent", "child", "other"] = "child"
    # 가입할 때 돌봄 위치 공유에 동의하는지(기본은 동의 안 함). 나중에 PUT /care/location/consent 로 바꿀 수 있다.
    location_consent: bool = False


class UserOut(BaseModel):
    id: str
    name: str
    role: str
    role_detail: str | None = None  # 역할이 other 일 때 직접 적은 관계
    active_group_id: str | None = None
    location_consent: bool = False
    # 정식 회원(아이디/비밀번호 가입) 정보. 개발용 익명 계정은 null / false.
    login_id: str | None = None
    email: str | None = None
    email_verified: bool = False
    photo_url: str | None = None  # 프로필 사진의 상대 경로(없으면 null). 같은 가족만 받을 수 있다


class AccountSignupIn(BaseModel):
    """회원가입 요청. 형식·규칙 검사는 credentials.py 에서 하고(공통 에러 코드), 여기서는 과도한 크기만 막는다."""

    login_id: str = Field(max_length=64)
    password: str = Field(max_length=256)
    email: str | None = Field(
        default=None, max_length=320
    )  # 선택. 없으면 이메일 인증·비밀번호 재설정 메일을 쓸 수 없다
    name: str = Field(max_length=80)
    role: Literal["parent", "child", "other"] = "child"
    role_detail: str | None = Field(default=None, max_length=80)  # role=other 일 때만 저장


class AccountSignupOut(BaseModel):
    user: UserOut


class LoginIn(BaseModel):
    login_id: str = Field(max_length=64)
    password: str = Field(max_length=256)
    device_label: str | None = Field(
        default=None, max_length=60
    )  # 세션 구분용 이름(예: "지민의 iPhone")


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Access Token 유효 시간(초)
    refresh_expires_in: int  # Refresh Token 유효 시간(초)


class LoginOut(TokenOut):
    user: UserOut


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=1024)


class EmailRequestIn(BaseModel):
    email: str = Field(max_length=320)


class TokenIn(BaseModel):
    token: str = Field(max_length=256)


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")  # 메일의 6자리 인증 코드


class EmailVerifiedOut(BaseModel):
    email_verified: bool = True


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class PasswordResetCodeConfirmIn(BaseModel):
    email: str = Field(max_length=320)
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(max_length=256)


class LoginIdAvailableOut(BaseModel):
    login_id: str  # 정규화(공백 제거·소문자)된 값
    available: bool


class SignupOut(BaseModel):
    user: UserOut
    token: str


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


class MemberOut(BaseModel):
    id: str
    name: str
    role: str  # 가입할 때 고른 역할(parent/child/other)
    group_role: str = "member"  # 이 가족 안의 권한(owner/admin/member). 요청으로 바꿀 수 없다
    display_name: str | None = None  # 이 가족에서 쓰는 표시 이름(없으면 name). 본인만 바꿀 수 있다
    family_relation: str | None = None  # mom|dad|son|daughter|grandma|grandpa|other
    family_relation_detail: str | None = None  # 관계가 other 일 때 직접 적은 관계
    photo_url: str | None = None  # 프로필 사진의 상대 경로(없으면 null)


class GroupOut(BaseModel):
    id: str
    name: str
    invite_code: str | None = None  # 가족 관리자(owner/admin)에게만 보인다
    invite_expires_at: datetime | None = None
    invite_uses_left: int | None = None  # 초대 코드로 더 들어올 수 있는 사람 수(관리자에게만, null = 제한 없음)
    invite_auto_approve: bool | None = None  # 초대로 들어온 사람을 바로 구성원으로 넣는지(관리자에게만)
    my_id: str | None = None  # 이 응답을 받는 사람의 사용자 id(구성원 목록에서 나를 찾을 때)
    my_role: str | None = None  # 이 응답을 받는 사람의 이 가족 안 권한(owner/admin/member)
    members: list[MemberOut]
