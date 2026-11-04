"""가족 초대·가입 승인(PR 4-B)의 요청·응답 모델."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class InviteOut(BaseModel):
    invite_code: str
    expires_at: datetime | None = None
    uses_left: int | None = None  # 이 코드로 더 들어올 수 있는 사람 수(null = 제한 없음)


class InviteSettingsIn(BaseModel):
    auto_approve: bool  # true 면 초대 코드로 들어온 사람을 관리자 승인 없이 바로 구성원으로 넣는다


class GroupNameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        """앞뒤 공백을 지우고, 공백뿐인 이름은 받지 않는다(가족 만들기와 같은 1~60자 규칙)."""
        value = value.strip()
        if not value:
            raise ValueError("가족 이름을 입력해 주세요")
        return value


class JoinRequestOut(BaseModel):
    """내가 낸 가입 요청. status: pending(승인 대기) | approved | rejected | cancelled."""

    id: str
    group_id: str
    group_name: str
    status: str
    requested_at: datetime
    decided_at: datetime | None = None


class PendingJoinOut(BaseModel):
    """관리자가 보는 승인 대기 요청."""

    id: str
    user_id: str
    user_name: str
    user_role: str  # 가입할 때 고른 역할(parent/child/other)
    requested_at: datetime
