import calendar
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.seed_lock import seed_lock

from . import repository as repo
from .models import (
    Allowance,
    AllowanceUse,
    BillingSettings,
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
    ManagerOut,
    MonthlyItem,
    MonthlyPlan,
    MonthlyResult,
    PaymentCreate,
    PaymentOut,
    Reminder,
    Settlement,
    SettleRequest,
    SettleTagOut,
    SubscriptionCreate,
    SubscriptionList,
    SubscriptionOut,
    SubscriptionPatch,
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


def _fixed_tags(members: list[User], minor_ids: list[str]):
    """정산 대상 고정 태그와 태그별 나눌 사람. 규칙을 바꾸려면 여기만 고친다.
    - 부모님 대상: 부모 역할이 아닌 구성원이 나눠 낸다.
    - 자녀 대상: 미성년 자녀가 있으면 부모님이 부담하고, 없으면 성인 자녀(child)끼리 나눈다.
    - 가족 전체: 모두."""
    has_minor = any(m.id in minor_ids for m in members)
    children = [m for m in members if m.role == ("parent" if has_minor else "child")]
    children_desc = "미성년 자녀 몫은 부모님이 부담해요" if has_minor else "성인 자녀끼리 나눠 내요"
    return (
        (
            "parents",
            "부모님 대상",
            "부모님 몫을 자녀들이 나눠 내요",
            [m for m in members if m.role != "parent"],
        ),
        ("children", "자녀 대상", children_desc, children),
        ("all", "가족 전체", "가족 모두가 나눠 내요", list(members)),
    )


REMINDER_DAYS = 5  # 월말 알림: 마지막 5일, 지난 달 지연 알림: 월초 5일


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
        settled=e.settled_at is not None,
        subscription_id=e.subscription_id,
    )


def create(db: Session, group_id: str, user_id: str, body: ExpenseCreate) -> ExpenseOut:
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
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
            paid_by=user_id,  # 요청 바디의 값은 받지 않는다: 로그인한 사용자가 낸 사람이다
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


def summary(db: Session, group_id: str, month: str, settled_only: bool = False) -> Summary:
    """그 달 지출을 지출마다 '나눌 사람'끼리 정수 원으로 나눈 사람별 잔액. 합계는 항상 0이다.
    settled_only=True 면 '정산하기'를 마친 지출만 센다(정산 화면). 기본은 미정산 지출까지 포함한 월 요약이다."""
    expenses = repo.list_month(db, group_id, month)
    if settled_only:
        expenses = [e for e in expenses if e.settled_at is not None]
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
    base = summary(db, group_id, month, settled_only=True)
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

    unsettled = [e for e in repo.list_month(db, group_id, month) if e.settled_at is None]
    return Settlement(
        month=month,
        balances=base.balances,
        unsettled_count=len(unsettled),
        unsettled_total=sum(e.amount for e in unsettled),
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
        SettleTagOut(key=key, label=label, description=desc, participants=[m.id for m in people])
        for key, label, desc, people in _fixed_tags(members, _minor_ids(db, group_id))
    ]


def settle(db: Session, group_id: str, user_id: str, body: SettleRequest) -> Settlement:
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
        people = next(
            f[3] for f in _fixed_tags(members, _minor_ids(db, group_id)) if f[0] == body.tag
        )
        participants = [m.id for m in people]
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
    now = datetime.now(UTC)
    for e in chosen:
        e.target_tag, e.split_among = body.tag, participants
        e.settled_at, e.settled_by = now, user_id
    repo.save_all(db, chosen)
    return settlement(db, group_id, month)


# ---- 정산 담당자와 월말 알림 ----


def _manager_id(db: Session, group_id: str) -> str:
    """정산 담당자 id. 지정하지 않았으면 그룹을 만든 사람이다."""
    row = repo.get_settings(db, group_id)
    if row is not None:
        return row.manager_id
    return group_repo.get_group(db, group_id).owner_id


def _minor_ids(db: Session, group_id: str) -> list[str]:
    row = repo.get_settings(db, group_id)
    return list(row.minor_ids or []) if row is not None else []


def _ensure_can_manage(db: Session, group_id: str, user: User) -> None:
    """정산 설정(담당자·미성년 표시) 변경은 지금 담당자나 그룹을 만든 사람만 할 수 있다."""
    owner_id = group_repo.get_group(db, group_id).owner_id
    if user.id not in (_manager_id(db, group_id), owner_id):
        raise ApiError(403, "not_manager", "정산 담당자나 그룹을 만든 사람만 바꿀 수 있어요")


def get_manager(db: Session, group_id: str, user: User) -> ManagerOut:
    manager_id = _manager_id(db, group_id)
    members = group_repo.members(db, group_id)
    name = next((m.name for m in members if m.id == manager_id), "")
    minors = [m.id for m in members if m.id in _minor_ids(db, group_id)]
    return ManagerOut(
        manager_id=manager_id, manager_name=name, is_me=manager_id == user.id, minor_ids=minors
    )


def set_manager(db: Session, group_id: str, user: User, new_id: str) -> ManagerOut:
    """담당자 변경은 지금 담당자나 그룹을 만든 사람만 할 수 있다."""
    _ensure_can_manage(db, group_id, user)
    if new_id not in [m.id for m in group_repo.members(db, group_id)]:
        raise bad_request("invalid_manager", "정산 담당자는 가족 구성원이어야 해요")
    row = repo.get_settings(db, group_id) or BillingSettings(group_id=group_id, manager_id=new_id)
    row.manager_id, row.updated_at = new_id, datetime.now(UTC)
    repo.save(db, row)
    return get_manager(db, group_id, user)


def set_minors(db: Session, group_id: str, user: User, user_ids: list[str]) -> ManagerOut:
    """미성년 자녀 표시. 부모 역할이 아닌 구성원만 고를 수 있다. 이 표시가 있으면 '자녀 대상' 정산은 부모님이 부담한다."""
    _ensure_can_manage(db, group_id, user)
    members = group_repo.members(db, group_id)
    allowed = {m.id for m in members if m.role != "parent"}
    if any(u not in allowed for u in user_ids):
        raise bad_request(
            "invalid_minor", "미성년 표시는 부모 역할이 아닌 가족 구성원만 할 수 있어요"
        )
    row = repo.get_settings(db, group_id) or BillingSettings(
        group_id=group_id, manager_id=_manager_id(db, group_id)
    )
    row.minor_ids = [m.id for m in members if m.id in set(user_ids)]
    row.updated_at = datetime.now(UTC)
    repo.save(db, row)
    return get_manager(db, group_id, user)


def reminder(db: Session, group_id: str, user: User, on: str | None) -> Reminder:
    """월말(마지막 5일)에는 이번 달, 월초(5일까지)에는 지난 달의 '정산하기를 안 한 지출'을 정산 담당자에게만 알린다.
    `on`(YYYY-MM-DD)을 주면 그 날짜를 오늘로 본다(화면 테스트용)."""
    try:
        today = datetime.strptime(on, "%Y-%m-%d").date() if on else datetime.now(KST).date()
    except ValueError:
        raise bad_request("invalid_date", "날짜는 YYYY-MM-DD 형식이어야 해요") from None
    last_day = calendar.monthrange(today.year, today.month)[1]
    days_left = last_day - today.day
    if days_left < REMINDER_DAYS:
        kind, month = "month_end", today.strftime("%Y-%m")
    elif today.day <= REMINDER_DAYS:
        prev = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        kind, month, days_left = "overdue", prev, None
    else:
        kind, month, days_left = None, None, None
    unsettled = (
        [e for e in repo.list_month(db, group_id, month) if e.settled_at is None] if month else []
    )
    manager = get_manager(db, group_id, user)
    return Reminder(
        show=manager.is_me and kind is not None and len(unsettled) > 0,
        is_manager=manager.is_me,
        manager_name=manager.manager_name,
        kind=kind,
        month=month,
        unsettled_count=len(unsettled),
        unsettled_total=sum(e.amount for e in unsettled),
        days_left=days_left if kind == "month_end" else None,
    )


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


MAX_SUBSCRIPTIONS = 30
SUBSCRIPTION_CATEGORY = "구독"


def _split_ids(split: list[str] | None, member_ids: list[str]) -> list[str]:
    """저장된 나눌 사람(비어 있으면 가족 전체)을 현재 구성원 순서로 풀어 낸다."""
    wanted = set(split or member_ids)
    return [u for u in member_ids if u in wanted] or member_ids


def _subscription_out(i: SubscriptionItem, members: list[User]) -> SubscriptionOut:
    names = {m.id: m.name for m in members}
    return SubscriptionOut(
        id=i.id,
        kind=i.kind,
        name=i.name,
        status=i.status,
        carrier=i.carrier,
        monthly_fee=i.monthly_fee,
        billing_day=i.billing_day,
        payer_id=i.payer_id,
        payer_name=names.get(i.payer_id, ""),
        split_among=_split_ids(i.split_among, [m.id for m in members]),
    )


def _ensure_default_subscriptions(db: Session, group_id: str) -> None:
    """처음 열 때 기본 항목을 만든다. 사용자가 다 지워도 다시 만들지 않는다."""
    if repo.has_subscriptions(db, group_id):
        return
    with seed_lock(db, f"subscriptions:{group_id}"):  # 동시 요청이 둘 다 만들지 않게 잠근다
        if repo.has_subscriptions(db, group_id):
            return
        repo.add_subscriptions(
            db,
            [
                SubscriptionItem(
                    id=uuid.uuid4().hex[:12], group_id=group_id, kind=k, name=n, sort_order=i
                )
                for i, (k, n) in enumerate(DEFAULT_SUBSCRIPTIONS)
            ],
        )


def list_subscriptions(db: Session, group_id: str) -> SubscriptionList:
    _ensure_default_subscriptions(db, group_id)
    items = repo.list_subscriptions(db, group_id)
    members = group_repo.members(db, group_id)
    return SubscriptionList(
        notice=SUBSCRIPTION_NOTICE,
        items=[_subscription_out(i, members) for i in items],
        monthly_total=sum(i.monthly_fee or 0 for i in items),
    )


def _check_carrier(kind: str, carrier: str | None) -> None:
    if carrier is not None and kind != "telecom":
        raise bad_request("invalid_carrier", "통신사는 통신비 항목에만 지정할 수 있어요")


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise bad_request("invalid_name", "이름을 입력해 주세요")
    return name


def _check_payer(payer_id: str | None, member_ids: list[str]) -> None:
    if payer_id is not None and payer_id not in member_ids:
        raise bad_request("invalid_payer", "결제한 사람은 가족 구성원이어야 해요")


def _clean_split(split: list[str] | None, member_ids: list[str]) -> list[str]:
    """비어 있으면(가족 전체) 빈 목록으로 저장한다. 구성원이 아닌 id 는 거절한다."""
    if not split:
        return []
    if any(u not in member_ids for u in split):
        raise bad_request("invalid_split", "나눌 사람은 가족 구성원이어야 해요")
    chosen = [u for u in member_ids if u in set(split)]
    return [] if len(chosen) == len(member_ids) else chosen


def create_subscription(
    db: Session, group_id: str, user: User, body: SubscriptionCreate
) -> SubscriptionOut:
    _ensure_default_subscriptions(db, group_id)
    _check_carrier(body.kind, body.carrier)
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
    # 보내지 않으면 등록한 사람이 결제하는 것으로 보고, null 을 명시하면 '결제한 사람 없음'으로 저장한다
    payer_id = body.payer_id if "payer_id" in body.model_fields_set else user.id
    _check_payer(payer_id, ids)
    split = _clean_split(body.split_among, ids)
    if len(repo.list_subscriptions(db, group_id)) >= MAX_SUBSCRIPTIONS:
        raise bad_request("too_many", f"항목은 {MAX_SUBSCRIPTIONS}개까지 만들 수 있어요")
    item = repo.save(
        db,
        SubscriptionItem(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            kind=body.kind,
            name=_clean_name(body.name),
            carrier=body.carrier,
            monthly_fee=body.monthly_fee,
            billing_day=body.billing_day,
            payer_id=payer_id,
            split_among=split,
            sort_order=repo.max_subscription_order(db, group_id) + 1,
        ),
    )
    return _subscription_out(item, members)


def update_subscription(
    db: Session, group_id: str, item_id: str, body: SubscriptionPatch
) -> SubscriptionOut:
    """보낸 필드만 바꾼다(금액·결제일·통신사·결제한 사람은 null 을 보내면 지운다, 나눌 사람은 빈 목록이면 가족 전체)."""
    sent = body.model_fields_set
    if not sent:
        raise bad_request("empty_patch", "바꿀 내용을 보내 주세요")
    item = repo.get_subscription(db, group_id, item_id)
    if item is None:
        raise not_found("항목")
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
    if "status" in sent and body.status is not None:
        item.status = body.status
    if "name" in sent and body.name is not None:
        item.name = _clean_name(body.name)
    if "carrier" in sent:
        _check_carrier(item.kind, body.carrier)
        item.carrier = body.carrier
    if "monthly_fee" in sent:
        item.monthly_fee = body.monthly_fee
    if "billing_day" in sent:
        item.billing_day = body.billing_day
    if "payer_id" in sent:
        _check_payer(body.payer_id, ids)
        item.payer_id = body.payer_id
    if "split_among" in sent:
        item.split_among = _clean_split(body.split_among, ids)
    item.updated_at = datetime.now(UTC)
    return _subscription_out(repo.save(db, item), members)


def delete_subscription(db: Session, group_id: str, item_id: str) -> None:
    item = repo.get_subscription(db, group_id, item_id)
    if item is None:
        raise not_found("항목")
    item.deleted_at = datetime.now(UTC)
    repo.save(db, item)


# ---- 구독료를 월별 지출로 만들기 ----


def _due_date(month: str, billing_day: int | None) -> str:
    """지출 날짜. 결제일이 없으면 1일, 그 달에 없는 날(예: 2월 31일)이면 그 달의 마지막 날이다."""
    year, mon = (int(x) for x in month.split("-"))
    last = calendar.monthrange(year, mon)[1]
    return f"{month}-{min(billing_day or 1, last):02d}"


def monthly_plan(db: Session, group_id: str, month: str) -> MonthlyPlan:
    """이번 달에 구독료 지출로 만들 수 있는 항목. 금액이 있고 결제한 사람이 있으며 아직 안 만든 항목만 ready 다."""
    month = check_month(month)
    _ensure_default_subscriptions(db, group_id)
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
    names = {m.id: m.name for m in members}
    made = repo.subscription_ids_with_expense(db, group_id, month)
    entries: list[MonthlyItem] = []
    for i in repo.list_subscriptions(db, group_id):
        if not i.monthly_fee:
            state = "no_fee"
        elif i.payer_id not in names:
            state = "no_payer"
        elif i.id in made:
            state = "created"
        else:
            state = "ready"
        entries.append(
            MonthlyItem(
                id=i.id,
                name=i.name,
                kind=i.kind,
                amount=i.monthly_fee,
                date=_due_date(month, i.billing_day),
                payer_name=names.get(i.payer_id, ""),
                split_count=len(_split_ids(i.split_among, ids)),
                state=state,
            )
        )
    ready = [e for e in entries if e.state == "ready"]
    return MonthlyPlan(
        month=month,
        items=entries,
        ready_count=len(ready),
        ready_total=sum(e.amount or 0 for e in ready),
    )


def generate_monthly(db: Session, group_id: str, month: str) -> MonthlyResult:
    """'이번 달 구독료 지출 만들기'. ready 인 항목만 지출로 만들고(미정산 상태), 같은 달에 다시 눌러도 중복으로 만들지 않는다."""
    plan = monthly_plan(db, group_id, month)
    members = group_repo.members(db, group_id)
    ids = [m.id for m in members]
    names = {m.id: m.name for m in members}
    items = {i.id: i for i in repo.list_subscriptions(db, group_id)}
    created: list[Expense] = []
    for entry in plan.items:
        if entry.state != "ready":
            continue
        item = items[entry.id]
        split = _split_ids(item.split_among, ids)
        created.append(
            Expense(
                id=uuid.uuid4().hex[:12],
                group_id=group_id,
                title=f"{item.name} 구독료",
                amount=item.monthly_fee,
                date=entry.date,
                category=SUBSCRIPTION_CATEGORY,
                paid_by=item.payer_id,
                split_among=split,
                target_tag="all" if set(split) == set(ids) else "custom",
                subscription_id=item.id,
            )
        )
    if created:
        repo.save_all(db, created)
    return MonthlyResult(
        created=[_expense_out(e, names, ids) for e in created],
        plan=monthly_plan(db, group_id, month),
    )


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
