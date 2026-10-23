from datetime import date as _date
from typing import Literal

from pydantic import BaseModel, Field

SubscriptionStatus = Literal["check", "available", "active"]  # 확인 필요 / 적용 가능 / 적용 중
Carrier = Literal["skt", "kt", "lgu", "mvno", "other"]  # SKT / KT / LG U+ / 알뜰폰 / 기타
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
    settled: bool = False  # 정산하기를 누른 지출인지
    subscription_id: str | None = None  # 구독료로 만든 지출이면 그 항목 id


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
    # 잔액·송금 목록에는 '정산하기'를 마친 지출만 들어간다. 아직 정산하지 않은 지출은 여기에 센다.
    unsettled_count: int = 0
    unsettled_total: int = 0


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


class ManagerOut(BaseModel):
    manager_id: str
    manager_name: str
    is_me: bool
    minor_ids: list[str] = []  # 미성년 자녀(자녀 대상 정산은 부모님이 부담)


class MinorsSet(BaseModel):
    user_ids: list[str]


class ManagerSet(BaseModel):
    user_id: str


class Reminder(BaseModel):
    """월말 정산 알림. 정산 담당자에게만 show=true 로 내려간다."""

    show: bool
    is_manager: bool
    manager_name: str
    kind: Literal["month_end", "overdue"] | None  # 월말(마지막 5일) / 지난 달 정산이 밀림(월초 5일)
    month: str | None
    unsettled_count: int
    unsettled_total: int
    days_left: int | None  # 월말까지 남은 일수(월말 알림일 때)


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
    carrier: Carrier | None = None
    monthly_fee: int | None = None  # 월 청구 금액(원): 청구서의 실제 금액(할인이 이미 빠진 값)
    discount_amount: int | None = None  # 결합 할인 금액(원): 직접 입력한 참고 값
    list_price: int | None = None  # 정가 = 월 청구 금액 + 할인 금액(둘 중 하나라도 입력했을 때)
    billing_day: int | None = None  # 매월 결제일
    payer_id: str | None = None  # 구독료 지출의 결제한 사람
    payer_name: str = ""
    split_among: list[
        str
    ] = []  # 나눌 사람(비어 있으면 가족 전체가 아니라 실제 전원 id 로 풀어서 내려준다)


class SubscriptionList(BaseModel):
    notice: str
    items: list[SubscriptionOut]
    monthly_total: int  # 월 청구 금액의 합(할인이 이미 빠진 값)
    discount_total: int = 0  # 직접 입력한 결합 할인 금액의 합


class CatalogEntry(BaseModel):
    kind: Literal["ott", "telecom"]
    name: str
    added: bool  # 이미 항목으로 추가했는지


class SubscriptionCatalog(BaseModel):
    items: list[CatalogEntry]


class SubscriptionCreate(BaseModel):
    kind: Literal["ott", "telecom"]
    name: str = Field(min_length=1, max_length=60)
    carrier: Carrier | None = None  # 통신비 항목만
    monthly_fee: int | None = Field(default=None, ge=0, le=10_000_000)
    discount_amount: int | None = Field(default=None, ge=0, le=10_000_000)
    billing_day: int | None = Field(default=None, ge=1, le=31)
    payer_id: str | None = (
        None  # 보내지 않으면 요청한 사람, null 이면 결제한 사람 없음(지출을 만들지 않는다)
    )
    split_among: list[str] | None = None  # 비우면 가족 전체


class SubscriptionPatch(BaseModel):
    """보낸 필드만 바꾼다. 금액·결제일·통신사는 null 을 보내면 지운다."""

    status: SubscriptionStatus | None = None
    name: str | None = Field(default=None, min_length=1, max_length=60)
    carrier: Carrier | None = None
    monthly_fee: int | None = Field(default=None, ge=0, le=10_000_000)
    discount_amount: int | None = Field(default=None, ge=0, le=10_000_000)
    billing_day: int | None = Field(default=None, ge=1, le=31)
    payer_id: str | None = None
    split_among: list[str] | None = None


class MonthlyItem(BaseModel):
    id: str
    name: str
    kind: Literal["ott", "telecom"]
    amount: int | None
    date: str  # 지출 날짜(결제일, 달 길이에 맞춰 줄인다. 결제일이 없으면 1일)
    payer_name: str
    split_count: int
    state: Literal[
        "ready", "created", "no_fee", "no_payer"
    ]  # 만들 수 있음 / 이미 만듦 / 금액 없음 / 결제한 사람 없음


class MonthlyPlan(BaseModel):
    month: str
    items: list[MonthlyItem]
    ready_count: int
    ready_total: int


class MonthlyGenerate(BaseModel):
    month: str


class MonthlyResult(BaseModel):
    created: list[ExpenseOut]
    plan: MonthlyPlan  # 만든 뒤의 상태


AllowanceCycle = Literal["weekly", "monthly"]
AllowanceMode = Literal["auto", "remind"]


class AllowancePlanIn(BaseModel):
    cycle: AllowanceCycle
    day: int = Field(ge=0, le=31)  # weekly: 0(월)~6(일), monthly: 1~31
    amount: int = Field(gt=0, le=10_000_000)
    mode: AllowanceMode


class AllowancePlanOut(BaseModel):
    cycle: AllowanceCycle
    day: int
    amount: int
    mode: AllowanceMode
    start_date: str
    next_due: str  # 다음 지급일(오늘 포함)


class AllowanceMoneyIn(BaseModel):
    amount: int = Field(gt=0, le=10_000_000)
    memo: str = Field(default="", max_length=120)
    date: _date | None = None  # 비우면 오늘(한국 시간). 미래 날짜는 안 된다.


class AllowancePayIn(BaseModel):
    due_date: _date  # 리마인드로 알린 지급일


class AllowanceEntryOut(BaseModel):
    id: str
    kind: Literal["credit", "use"]
    amount: int
    memo: str
    date: str
    source: Literal["manual", "plan_auto", "plan_remind"]
    by_name: str  # 기록한 사람(자동이면 "자동 지급")
    voided: bool
    balance_after: int | None  # 이 줄까지 반영한 잔액(취소된 줄은 None)


class AllowancePending(BaseModel):
    due_date: str
    amount: int


class AllowanceOut(BaseModel):
    child_id: str
    name: str
    balance: int  # 지금 잔액(취소된 줄 제외)
    total_credit: int
    total_use: int
    plan: AllowancePlanOut | None = None
    pending: list[AllowancePending]  # 리마인드 방식에서 아직 "지급했어요"를 누르지 않은 지급일
    entries: list[AllowanceEntryOut]  # 최신순
    can_manage: bool  # 지금 사용자가 주기·지급·취소를 할 수 있는지(부모 역할 또는 그룹을 만든 사람)
    can_record_use: bool  # 지금 사용자가 사용 내역을 기록할 수 있는지(본인 또는 관리 권한자)
