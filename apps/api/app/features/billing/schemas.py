from datetime import date as _date
from typing import Literal

from pydantic import BaseModel, Field

SubscriptionStatus = Literal["check", "available", "active"]  # 확인 필요 / 적용 가능 / 적용 중
FixedTag = Literal["parents", "children", "all"]
TargetTag = Literal["parents", "children", "all", "custom"]  # custom: 직접 고르기


class ExpenseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    amount: int = Field(gt=0)
    date: _date
    category: str = "기타"
    split_among: list[str] | None = None  # 비우면 가족 전원


class ExpenseOut(BaseModel):
    id: str
    title: str
    amount: int
    date: str
    category: str
    paid_by: str
    paid_by_name: str = ""
    split_among: list[str] = []
    target_tag: str = "all"


class Balance(BaseModel):
    user_id: str
    name: str
    paid: int
    share: int  # 내가 나눠 낼 몫의 합계
    balance: int  # 양수: 받을 돈, 음수: 낼 돈
    remaining: int = 0  # 송금 완료분을 반영한 남은 잔액


class Summary(BaseModel):
    month: str
    total: int
    count: int
    balances: list[Balance]


class Transfer(BaseModel):
    from_user_id: str
    from_name: str
    to_user_id: str
    to_name: str
    amount: int


class PaymentOut(Transfer):
    id: str


class Settlement(BaseModel):
    month: str
    balances: list[Balance]
    transfers: list[Transfer]  # 아직 보내지 않은 최소 송금 목록
    completed: list[PaymentOut]  # 송금 완료로 표시한 것


class SettleTagOut(BaseModel):
    key: FixedTag
    label: str
    description: str
    participants: list[str]  # 이 태그를 고르면 기본으로 채워지는 나눌 사람


class SettleRequest(BaseModel):
    month: str
    expense_ids: list[str] = Field(min_length=1)
    tag: TargetTag
    participants: list[str] | None = None  # 직접 고르기(custom)일 때만 쓴다


class PaymentCreate(BaseModel):
    month: str
    from_user_id: str
    to_user_id: str
    amount: int = Field(gt=0)


class SubscriptionOut(BaseModel):
    id: str
    kind: Literal["ott", "telecom"]
    name: str
    status: SubscriptionStatus


class SubscriptionList(BaseModel):
    notice: str
    items: list[SubscriptionOut]


class SubscriptionPatch(BaseModel):
    status: SubscriptionStatus


class AllowanceBudget(BaseModel):
    month: str | None = None  # 비우면 이번 달
    budget: int = Field(ge=0)


class AllowanceUseCreate(BaseModel):
    amount: int = Field(gt=0)
    memo: str = Field(default="", max_length=120)
    date: _date | None = None  # 비우면 오늘(한국 시간)


class AllowanceUseOut(BaseModel):
    id: str
    amount: int
    memo: str
    date: str


class AllowanceOut(BaseModel):
    child_id: str
    name: str
    month: str
    budget: int | None  # 아직 정하지 않았으면 None
    used: int
    remaining: int
    uses: list[AllowanceUseOut]
