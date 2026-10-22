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
    active_group_id: str | None = None
    location_consent: bool = False
    # 정식 회원(아이디/비밀번호 가입) 정보. 개발용 익명 계정은 null / false.
    login_id: str | None = None
    email: str | None = None
    email_verified: bool = False


class AccountSignupIn(BaseModel):
    """회원가입 요청. 형식·규칙 검사는 credentials.py 에서 하고(공통 에러 코드), 여기서는 과도한 크기만 막는다."""

    login_id: str = Field(max_length=64)
    password: str = Field(max_length=256)
    email: str = Field(max_length=320)
    name: str = Field(max_length=80)
    role: Literal["parent", "child", "other"] = "child"


class AccountSignupOut(BaseModel):
    user: UserOut


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
    role: str


class GroupOut(BaseModel):
    id: str
    name: str
    invite_code: str | None = None
    members: list[MemberOut]
