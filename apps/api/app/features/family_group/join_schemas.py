"""가족 초대·가입 승인(PR 4-B)의 요청·응답 모델."""

from datetime import datetime

from pydantic import BaseModel


class InviteOut(BaseModel):
    invite_code: str
    expires_at: datetime | None = None


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
