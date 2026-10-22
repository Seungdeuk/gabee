import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.features.family_group.models import User
from app.shared.errors import bad_request, not_found

from . import repository as repo
from .models import (
    Allowance,
    AllowanceUse,
    Expense,
    SettlementPayment,
    SubscriptionItem,
)
from .schemas import (
    AllowanceOut,
    AllowanceUseCreate,
    AllowanceUseOut,
    Balance,
    ExpenseCreate,
    ExpenseOut,
    PaymentCreate,
    PaymentOut,
    Settlement,
    SettleRequest,
    SettleTagOut,
    SubscriptionList,
    SubscriptionOut,
    Summary,
    Transfer,
)
from .settlement import minimal_transfers, split_equally

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KST = timezone(timedelta(hours=9))

SUBSCRIPTION_NOTICE = "예시, 실제 적용은 통신사에서 확인"
# 처음 열 때 만들어 두는 항목. 할인 금액은 다루지 않고 상태만 기록한다.
DEFAULT_SUBSCRIPTIONS = (
    ("ott", "넷플릭스"),
    ("ott", "유튜브 프리미엄"),
    ("ott", "디즈니+"),
    ("telecom", "가족 결합 할인"),
    ("telecom", "요금제 결합 할인"),
)


# 정산 대상 태그. 나눌 사람은 역할로 정한다. 규칙을 바꾸려면 여기만 고친다.
FIXED_TAGS = (
    ("parents", "부모님 대상", "부모님 몫을 자녀들이 나눠 내요", lambda m: m.role != "parent"),
    ("children", "자녀 대상", "자녀끼리 나눠 내요", lambda m: m.role == "child"),
    ("all", "가족 전체", "가족 모두가 나눠 내요", lambda m: True),
)


def check_month(month: str) -> str:
    if not _MONTH.match(month):
        raise bad_request("invalid_month", "월은 YYYY-MM 형식이어야 해요")
    return month


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def this_month() -> str:
    return today_kst()[:7]


# ---- 지출 ----


def _expense_out(e: Expense, names: dict[str, str], member_ids: list[str]) -> ExpenseOut:
    return ExpenseOut(
        id=e.id,
        title=e.title,
        amount=e.amount,
        date=e.date,
        category=e.category,
        paid_by=e.paid_by,
        paid_by_name=names.get(e.paid_by, ""),
        split_among=e.split_among or member_ids,
        target_tag=e.target_tag,
    )


def create(db: Session, group_id: str, user_id: str, body: ExpenseCreate) -> ExpenseOut:
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
    paid_by = body.paid_by or user_id
    if paid_by not in ids:
        raise bad_request("invalid_payer", "낸 사람은 가족 구성원이어야 해요")
    if body.split_among is None:
        split = ids
    else:
        if not body.split_among:
            raise bad_request("empty_split", "나눌 사람을 한 명 이상 골라 주세요")
        if any(u not in ids for u in body.split_among):
            raise bad_request("invalid_split", "나눌 사람은 가족 구성원이어야 해요")
        split = [u for u in ids if u in set(body.split_among)]  # 구성원 순서로 맞춰 둔다
    tag = "all" if body.split_among is None or set(split) == set(ids) else "custom"
    expense = repo.add(
        db,
        Expense(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            paid_by=paid_by,
            title=body.title.strip(),
            amount=body.amount,
            date=body.date.isoformat(),
            category=body.category,
            split_among=split,
            target_tag=tag,
        ),
    )
    return _expense_out(expense, {m.id: m.name for m in members}, ids)


def list_expenses(db: Session, group_id: str, month: str) -> list[ExpenseOut]:
    members = group_repo.members(db, group_id)
    names, ids = {m.id: m.name for m in members}, [m.id for m in members]
    return [_expense_out(e, names, ids) for e in repo.list_month(db, group_id, month)]


def delete_expense(db: Session, group_id: str, expense_id: str) -> None:
    expense = repo.get_expense(db, group_id, expense_id)
    if expense is None:
        raise not_found("지출")
    expense.deleted_at = datetime.now(UTC)
    repo.save(db, expense)


# ---- 정산 ----


def summary(db: Session, group_id: str, month: str) -> Summary:
    """그 달 지출을 지출마다 '나눌 사람'끼리 정수 원으로 나눈 사람별 잔액. 합계는 항상 0이다."""
    expenses = repo.list_month(db, group_id, month)
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
    paid = dict.fromkeys(ids, 0)
    owed = dict.fromkeys(ids, 0)
    for e in expenses:
        wanted = set(e.split_among or ids)
        participants = [u for u in ids if u in wanted] or ids
        for uid, amount in split_equally(e.amount, participants).items():
            owed[uid] += amount
        if e.paid_by in paid:
            paid[e.paid_by] += e.amount
    balances = [
        Balance(
            user_id=m.id,
            name=m.name,
            paid=paid[m.id],
            share=owed[m.id],
            balance=paid[m.id] - owed[m.id],
            remaining=paid[m.id] - owed[m.id],
        )
        for m in members
    ]
    return Summary(
        month=month, total=sum(e.amount for e in expenses), count=len(expenses), balances=balances
    )


def _remaining(db: Session, group_id: str, month: str):
    """송금 완료분을 반영한 남은 잔액. 보낸 사람은 잔액이 늘고 받은 사람은 줄어 합계는 그대로 0이다."""
    base = summary(db, group_id, month)
    remaining = {b.user_id: b.balance for b in base.balances}
    payments = repo.list_payments(db, group_id, month)
    for p in payments:
        if p.from_user_id in remaining:
            remaining[p.from_user_id] += p.amount
        if p.to_user_id in remaining:
            remaining[p.to_user_id] -= p.amount
    for b in base.balances:
        b.remaining = remaining[b.user_id]
    return base, remaining, payments


def settlement(db: Session, group_id: str, month: str) -> Settlement:
    base, remaining, payments = _remaining(db, group_id, month)
    names = {b.user_id: b.name for b in base.balances}

    def transfer(from_id: str, to_id: str, amount: int) -> Transfer:
        return Transfer(
            from_user_id=from_id,
            from_name=names.get(from_id, ""),
            to_user_id=to_id,
            to_name=names.get(to_id, ""),
            amount=amount,
        )

    return Settlement(
        month=month,
        balances=base.balances,
        transfers=[transfer(*t) for t in minimal_transfers(remaining)],
        completed=[
            PaymentOut(id=p.id, **transfer(p.from_user_id, p.to_user_id, p.amount).model_dump())
            for p in payments
        ],
    )


def settle_tags(db: Session, group_id: str) -> list[SettleTagOut]:
    """고정 태그와, 태그를 고르면 기본으로 채워지는 나눌 사람."""
    members = group_repo.members(db, group_id)
    return [
        SettleTagOut(
            key=key, label=label, description=desc, participants=[m.id for m in members if pick(m)]
        )
        for key, label, desc, pick in FIXED_TAGS
    ]


def settle(db: Session, group_id: str, body: SettleRequest) -> Settlement:
    """'정산하기': 고른 지출에 대상 태그를 걸고 나눌 사람을 정한다. 잔액과 송금 목록은 기존 계산을 그대로 쓴다.
    고정 태그는 역할로 나눌 사람을 채우고, 직접 고르기(custom)는 보낸 사람 목록을 그대로 쓴다."""
    month = check_month(body.month)
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
    if body.tag == "custom":
        if not body.participants:
            raise bad_request("empty_split", "나눌 사람을 한 명 이상 골라 주세요")
        if any(u not in ids for u in body.participants):
            raise bad_request("invalid_split", "나눌 사람은 가족 구성원이어야 해요")
        participants = [u for u in ids if u in set(body.participants)]
    else:
        pick = next(f[3] for f in FIXED_TAGS if f[0] == body.tag)
        participants = [m.id for m in members if pick(m)]
        if not participants:
            raise bad_request("no_participants", "이 태그에 해당하는 구성원이 없어요")
    if repo.list_payments(db, group_id, month):
        raise bad_request(
            "settlement_locked", "송금 완료 표시가 있는 달은 먼저 송금 완료를 취소해 주세요"
        )
    by_id = {e.id: e for e in repo.list_month(db, group_id, month)}
    unknown = [i for i in body.expense_ids if i not in by_id]
    if unknown:
        raise bad_request("unknown_expense", "이 달에 없는 지출이 들어 있어요")
    chosen = [by_id[i] for i in dict.fromkeys(body.expense_ids)]
    for e in chosen:
        e.target_tag, e.split_among = body.tag, participants
    repo.save_all(db, chosen)
    return settlement(db, group_id, month)


def mark_paid(db: Session, group_id: str, body: PaymentCreate) -> Settlement:
    month = check_month(body.month)
    _, remaining, _ = _remaining(db, group_id, month)
    if (body.from_user_id, body.to_user_id, body.amount) not in minimal_transfers(remaining):
        raise bad_request(
            "unknown_transfer", "송금 목록에 없는 송금이에요. 목록을 새로고침해 주세요"
        )
    repo.save(
        db,
        SettlementPayment(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            month=month,
            from_user_id=body.from_user_id,
            to_user_id=body.to_user_id,
            amount=body.amount,
        ),
    )
    return settlement(db, group_id, month)


def undo_paid(db: Session, group_id: str, payment_id: str) -> Settlement:
    payment = repo.get_payment(db, group_id, payment_id)
    if payment is None:
        raise not_found("송금 완료 기록")
    month = payment.month
    repo.delete(db, payment)
    return settlement(db, group_id, month)


# ---- 구독·통신비 가족 할인 상태 ----


def _subscription_out(i: SubscriptionItem) -> SubscriptionOut:
    return SubscriptionOut(id=i.id, kind=i.kind, name=i.name, status=i.status)


def list_subscriptions(db: Session, group_id: str) -> SubscriptionList:
    items = repo.list_subscriptions(db, group_id)
    if not items:
        items = [
            SubscriptionItem(
                id=uuid.uuid4().hex[:12], group_id=group_id, kind=k, name=n, sort_order=i
            )
            for i, (k, n) in enumerate(DEFAULT_SUBSCRIPTIONS)
        ]
        repo.add_subscriptions(db, items)
    return SubscriptionList(notice=SUBSCRIPTION_NOTICE, items=[_subscription_out(i) for i in items])


def set_subscription_status(
    db: Session, group_id: str, item_id: str, status: str
) -> SubscriptionOut:
    item = repo.get_subscription(db, group_id, item_id)
    if item is None:
        raise not_found("항목")
    item.status, item.updated_at = status, datetime.now(UTC)
    return _subscription_out(repo.save(db, item))


# ---- 용돈 ----


def _children(db: Session, group_id: str) -> list[User]:
    return [m for m in group_repo.members(db, group_id) if m.role != "parent"]


def _allowance_out(db: Session, child: User, month: str, allowance: Allowance | None):
    if allowance is None:
        return AllowanceOut(
            child_id=child.id,
            name=child.name,
            month=month,
            budget=None,
            used=0,
            remaining=0,
            uses=[],
        )
    used = repo.allowance_used(db, allowance.id)
    return AllowanceOut(
        child_id=child.id,
        name=child.name,
        month=month,
        budget=allowance.budget,
        used=used,
        remaining=allowance.budget - used,
        uses=[
            AllowanceUseOut(id=u.id, amount=u.amount, memo=u.memo, date=u.date)
            for u in repo.list_uses(db, allowance.id)
        ],
    )


def list_allowances(db: Session, group_id: str, month: str) -> list[AllowanceOut]:
    return [
        _allowance_out(db, c, month, repo.get_allowance(db, group_id, c.id, month))
        for c in _children(db, group_id)
    ]


def _child(db: Session, group_id: str, child_id: str) -> User:
    child = next((c for c in _children(db, group_id) if c.id == child_id), None)
    if child is None:
        raise not_found("자녀")
    return child


def set_budget(db: Session, group_id: str, child_id: str, month: str, budget: int) -> AllowanceOut:
    child = _child(db, group_id, child_id)
    allowance = repo.get_allowance(db, group_id, child_id, month)
    if allowance is None:
        allowance = Allowance(
            id=uuid.uuid4().hex[:12], group_id=group_id, child_id=child_id, month=month, budget=0
        )
    elif budget < repo.allowance_used(db, allowance.id):
        raise bad_request("budget_below_used", "이미 쓴 금액보다 예산을 낮출 수 없어요")
    allowance.budget = budget
    return _allowance_out(db, child, month, repo.save(db, allowance))


def add_use(db: Session, group_id: str, child_id: str, body: AllowanceUseCreate) -> AllowanceOut:
    child = _child(db, group_id, child_id)
    day = body.date.isoformat() if body.date else today_kst()
    month = day[:7]
    allowance = repo.get_allowance(db, group_id, child_id, month)
    if allowance is None:
        raise bad_request("no_budget", f"{month} 용돈 예산을 먼저 정해 주세요")
    remaining = allowance.budget - repo.allowance_used(db, allowance.id)
    if body.amount > remaining:
        raise bad_request(
            "over_budget", f"남은 금액({remaining:,}원)보다 큰 사용은 저장할 수 없어요"
        )
    repo.save(
        db,
        AllowanceUse(
            id=uuid.uuid4().hex[:12],
            allowance_id=allowance.id,
            amount=body.amount,
            memo=body.memo.strip(),
            date=day,
        ),
    )
    return _allowance_out(db, child, month, allowance)
