"""가족 프로필·별명·관리자 지정(PR 4-C)의 요청·응답 모델."""

from typing import Literal

from pydantic import BaseModel, Field

Relation = Literal["mom", "dad", "son", "daughter", "grandma", "grandpa", "other"]


class ProfileIn(BaseModel):
    """내 가족 프로필 수정. 보낸 항목만 바꾸고(보내지 않은 항목은 그대로), null/빈 문자열은 지운다."""

    display_name: str | None = Field(default=None, max_length=80)
    family_relation: Relation | None = None
    family_relation_detail: str | None = Field(default=None, max_length=80)


class RoleIn(BaseModel):
    """owner 로 올리는 값은 받지 않는다(소유권 이전은 이번 범위 밖)."""

    role: Literal["admin", "member"]


class NicknameIn(BaseModel):
    nickname: str | None = Field(default=None, max_length=80)
    memo: str | None = Field(default=None, max_length=1000)


class NicknameOut(BaseModel):
    target_user_id: str
    nickname: str | None = None
    memo: str | None = None
