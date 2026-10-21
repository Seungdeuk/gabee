from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: Literal["parent", "child", "other"] = "child"


class UserOut(BaseModel):
    id: str
    name: str
    role: str
    active_group_id: str | None = None


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
