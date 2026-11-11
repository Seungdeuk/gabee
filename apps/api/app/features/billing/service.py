import calendar
import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.notifications import notify
from app.shared.seed_lock import seed_lock

from . import allowance
from . import repository as repo
from .models import (
    AllowanceEntry,
    AllowancePlan,
    AllowanceRequest,
    BillingSettings,
    Expense,
    SettlementPayment,
    SubscriptionItem,
)
from .schemas import (
    AllowanceApproveIn,
    AllowanceEntryOut,
    AllowanceMoneyIn,
    AllowanceMonth,
    AllowanceOut,
    AllowancePayIn,
    AllowancePending,
    AllowancePlanIn,
    AllowancePlanOut,
    AllowanceRejectIn,
    AllowanceRequestIn,
    AllowanceRequestOut,
    Balance,
    CatalogEntry,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
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
    SubscriptionCatalog,
    SubscriptionCreate,
    SubscriptionList,
    SubscriptionOut,
    SubscriptionPatch,
    Summary,
    Transfer,
    UpcomingPayment,
    UpcomingPayments,
)
from .settlement import minimal_transfers, split_equally

log = logging.getLogger(__name__)

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KST = timezone(timedelta(hours=9))

SUBSCRIPTION_NOTICE = "예시, 실제 적용은 통신사에서 확인"
# 고를 수 있는 목록. 화면에는 사용자가 골라 추가한 항목만 나오고, 아직 안 쓰는 서비스는 이 목록에만 있다.
SUBSCRIPTION_CATALOG = (
    ("ott", "넷플릭스"),
    ("ott", "유튜브 프리미엄"),
    ("ott", "디즈니+"),
    ("ott", "티빙"),
    ("ott", "웨이브"),
    ("ott", "쿠팡플레이"),
    ("ott", "왓챠"),
    ("ott", "애플 TV+"),
    ("ott", "스포티파이"),
    ("ott", "멜론"),
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
UPCOMING_DAYS = 3  # 결제일 알림: 결제일 3일 전부터(오늘 포함)


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


def update_expense(db: Session, group_id: str, expense_id: str, body: ExpenseUpdate) -> ExpenseOut:
    """지출의 제목·금액·날짜·카테고리를 고친다(보낸 값만). 나눌 사람·낸 사람·정산 상태는 건드리지 않는다.
    누가 고칠 수 있는지는 부르는 쪽이 정한다(에이전트: 내가 낸 지출만)."""
    expense = repo.get_expense(db, group_id, expense_id)
    if expense is None:
        raise not_found("지출")
    sent = body.model_dump(exclude_none=True)
    if "title" in sent:
        expense.title = sent["title"].strip()
    if "amount" in sent:
        expense.amount = sent["amount"]
    if "date" in sent:
        expense.date = sent["date"].isoformat()
    if "category" in sent:
        expense.category = sent["category"]
    repo.save(db, expense)
    members = group_repo.members(db, group_id)
    return _expense_out(expense, {m.id: m.name for m in members}, [m.id for m in members])


def open_own_expense(
    db: Session, group_id: str, user_id: str, expense_id: str, verb: str
) -> Expense:
    """지우거나 고칠 수 있는 지출인지 본다. 에이전트의 제안·실행과 앱의 지출 수정(REST)이 같은 규칙을 쓴다.
    내가 낸 지출만, 정산하기를 마치지 않은 것만, 그 달에 송금 완료 표시가 없을 때만. verb 는 '지울'/'고칠'.
    규칙에 어긋나면 사용자에게 보여 줄 문장으로 ValueError 를 낸다."""
    expense = repo.get_expense(db, group_id, expense_id)
    if expense is None:
        raise ValueError("그런 지출이 없어요")
    if expense.paid_by != user_id:
        raise ValueError(
            f"내가 낸 지출만 {verb} 수 있어요. 다른 사람의 지출은 돌봄 탭의 정산·용돈에서 그 사람이 직접 해야 해요"
        )
    if expense.settled_at is not None:
        raise ValueError(
            f"정산하기를 마친 지출은 {verb} 수 없어요. 돌봄 탭의 정산·용돈에서 정산을 먼저 확인해 주세요"
        )
    if repo.list_payments(db, group_id, expense.date[:7]):
        raise ValueError(
            f"이 달에 송금 완료 표시가 있어서 {verb} 수 없어요. 송금 완료를 먼저 취소해 주세요"
        )
    return expense


def plan_expense_update(
    db: Session, group_id: str, user_id: str, expense_id: str, raw: dict
) -> tuple[Expense, dict, dict]:
    """수정할 지출과 '실제로 바뀌는 값'을 검증해서 (지출, 이전 값, 바뀌는 값)으로 돌려준다. 아직 저장하지 않는다.
    raw 는 title·amount·date(YYYY-MM-DD 글자)·category 중 보낸 것. 에이전트의 제안·실행과 앱의 수정이 같이 쓴다.
    다른 달로 옮기면 옮기려는 달에도 송금 완료 표시가 없어야 한다. 규칙에 어긋나면 ValueError."""
    expense = open_own_expense(db, group_id, user_id, expense_id, "고칠")
    new = ExpenseUpdate.model_validate(raw).model_dump(mode="json", exclude_none=True)
    if "title" in new:
        new["title"] = new["title"].strip()
        if not new["title"]:
            raise ValueError("제목을 비울 수 없어요")
    old = {
        "title": expense.title,
        "amount": expense.amount,
        "date": expense.date,
        "category": expense.category,
    }
    changes = {k: v for k, v in new.items() if v != old[k]}
    if not changes:
        raise ValueError("지금 값과 같아서 바뀌는 것이 없어요")
    new_date = changes.get("date")
    if (
        new_date
        and new_date[:7] != expense.date[:7]
        and repo.list_payments(db, group_id, new_date[:7])
    ):
        raise ValueError("옮기려는 달에 송금 완료 표시가 있어서 고칠 수 없어요")
    return expense, old, changes


def update_my_expense(
    db: Session, group_id: str, user_id: str, expense_id: str, body: ExpenseUpdate
) -> ExpenseOut:
    """앱의 지출 수정(PATCH). 없는 지출은 404, 규칙에 어긋나면 400 `expense_not_editable` 이다."""
    if repo.get_expense(db, group_id, expense_id) is None:
        raise not_found("지출")
    try:
        _, _, changes = plan_expense_update(
            db, group_id, user_id, expense_id, body.model_dump(mode="json", exclude_none=True)
        )
    except ValueError as e:
        raise bad_request("expense_not_editable", str(e)) from None
    return update_expense(db, group_id, expense_id, ExpenseUpdate.model_validate(changes))


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


def _notify_billing(
    db: Session,
    group_id: str,
    actor_id: str | None,
    event: str,
    title: str,
    recipients: list[str],
    target_type: str,
    target_id: str,
) -> None:
    """정산·용돈 사건을 알림함에 남긴다(고정 문구, 금액·이름·메모는 담지 않는다). 행동한 본인은 notify 가 뺀다."""
    notify(
        db,
        group_id=group_id,
        kind="billing",
        event=event,
        recipients=recipients,
        title=title,
        target_type=target_type,
        target_id=target_id,
        actor_user_id=actor_id,
    )
    db.commit()


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
    payers = [e.paid_by for e in chosen]  # 나눌 사람에 없어도 지출을 낸 사람은 잔액이 바뀐다
    _notify_billing(
        db,
        group_id,
        user_id,
        "settlement_updated",
        "정산 내역이 업데이트됐어요",
        list(dict.fromkeys([*participants, *payers])),
        "billing_month",
        month,
    )
    return settlement(db, group_id, month)


def check_settlement_reminders(
    db: Session, group_id: str, user: User, now: datetime | None = None
) -> int:
    """홈을 연 본인의 정산 재알림을 확인해, 대상이면 알림함에 한 줄 남기고 만든 개수를 돌려준다.

    대상: 정산하기 알림(settlement_updated)을 받은 지 `settlement_remind_hours` 시간이 지났고, 그 달에 보낼 돈이 아직 남았고,
    그 달 재알림(settlement_remind)을 받은 적이 없는 사람. 재알림을 보냈다는 기록은 알림함의 그 줄 자체다(DB 열 추가 없음).
    홈을 연 본인 몫만 만든다(가족 다른 사람의 것은 만들지 않는다). 두 기기가 동시에 열면 드물게 두 번 생길 수 있다(유니크 제약이 없다).
    알림 표가 없거나 어떤 오류가 나도 홈과 정산에는 영향이 없게 0 을 돌려준다. 문구는 고정 템플릿이고 금액은 넣지 않는다."""
    now = now or datetime.now(UTC)
    wait = timedelta(hours=settings.settlement_remind_hours)
    try:
        with db.begin_nested():
            rows = repo.settlement_notice_rows(db, group_id, user.id)
            sent = {month for event, month, _ in rows if event == "settlement_remind"}
            first_pay: dict[str, datetime] = {}
            for event, month, made_at in rows:
                if event != "settlement_updated" or not month or month in sent:
                    continue
                made_at = made_at if made_at.tzinfo else made_at.replace(tzinfo=UTC)
                if month not in first_pay or made_at < first_pay[month]:
                    first_pay[month] = made_at
            created = 0
            for month, made_at in sorted(first_pay.items()):
                if now - made_at < wait:
                    continue
                transfers = settlement(db, group_id, month).transfers
                if not any(t.from_user_id == user.id for t in transfers):
                    continue  # 송금 완료를 눌렀거나 더 보낼 돈이 없다
                created += notify(
                    db,
                    group_id=group_id,
                    kind="billing",
                    event="settlement_remind",
                    recipients=[user.id],
                    title="정산 송금이 아직 남았어요",
                    body=f"{month} 정산에서 보낼 돈이 있어요",
                    target_type="billing_month",
                    target_id=month,
                )
        if created:
            db.commit()
        return created
    except Exception as exc:  # 개인 정보는 남기지 않는다(예외 종류만)
        log.warning("settlement reminder check failed error=%s", type(exc).__name__)
        return 0


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


def mark_paid(db: Session, group_id: str, body: PaymentCreate, actor_id: str | None) -> Settlement:
    month = check_month(body.month)
    _, remaining, _ = _remaining(db, group_id, month)
    if (body.from_user_id, body.to_user_id, body.amount) not in minimal_transfers(remaining):
        raise bad_request(
            "unknown_transfer", "송금 목록에 없는 송금이에요. 목록을 새로고침해 주세요"
        )
    payment = SettlementPayment(
        id=uuid.uuid4().hex[:12],
        group_id=group_id,
        month=month,
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        amount=body.amount,
    )
    repo.save(db, payment)
    _notify_billing(
        db,
        group_id,
        actor_id,
        "payment_marked",
        "송금 완료가 표시됐어요",
        [body.from_user_id, body.to_user_id],
        "billing_month",
        month,
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
        discount_amount=i.discount_amount,
        list_price=None
        if i.monthly_fee is None and i.discount_amount is None
        else (i.monthly_fee or 0) + (i.discount_amount or 0),
        billing_day=i.billing_day,
        payer_id=i.payer_id,
        payer_name=names.get(i.payer_id, ""),
        split_among=_split_ids(i.split_among, [m.id for m in members]),
    )


def subscription_catalog(db: Session, group_id: str) -> SubscriptionCatalog:
    """고를 수 있는 서비스 목록. 이미 추가한 것은 `added` 로 표시한다(이름 기준)."""
    have = {(i.kind, i.name) for i in repo.list_subscriptions(db, group_id)}
    return SubscriptionCatalog(
        items=[CatalogEntry(kind=k, name=n, added=(k, n) in have) for k, n in SUBSCRIPTION_CATALOG]
    )


def list_subscriptions(db: Session, group_id: str) -> SubscriptionList:
    items = repo.list_subscriptions(db, group_id)
    members = group_repo.members(db, group_id)
    return SubscriptionList(
        notice=SUBSCRIPTION_NOTICE,
        items=[_subscription_out(i, members) for i in items],
        monthly_total=sum(i.monthly_fee or 0 for i in items),
        discount_total=sum(i.discount_amount or 0 for i in items),
    )


def upcoming_payments(db: Session, group_id: str, user: User, on: str | None) -> UpcomingPayments:
    """결제일이 3일 안(오늘 포함)으로 다가온 구독을 **결제한 사람에게만** 알린다.
    결제일이 없거나 결제한 사람이 없는 항목은 대상이 아니다. `on`(YYYY-MM-DD)은 화면 테스트용 오늘 날짜."""
    try:
        today = datetime.strptime(on, "%Y-%m-%d").date() if on else datetime.now(KST).date()
    except ValueError:
        raise bad_request("invalid_date", "날짜는 YYYY-MM-DD 형식이어야 해요") from None
    items: list[UpcomingPayment] = []
    for i in repo.list_subscriptions(db, group_id):
        if i.payer_id != user.id or i.billing_day is None:
            continue
        due = allowance.next_due("monthly", i.billing_day, today)  # 매월 같은 날(없으면 말일) 규칙
        days_left = (due - today).days
        if days_left > UPCOMING_DAYS:
            continue
        made = i.id in repo.subscription_ids_with_expense(db, group_id, due.strftime("%Y-%m"))
        items.append(
            UpcomingPayment(
                id=i.id,
                kind=i.kind,
                name=i.name,
                amount=i.monthly_fee,
                due_date=due.isoformat(),
                days_left=days_left,
                expense_made=made,
            )
        )
    items.sort(key=lambda x: (x.days_left, x.name))
    return UpcomingPayments(show=bool(items), within_days=UPCOMING_DAYS, items=items)


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
            discount_amount=body.discount_amount,
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
    if "discount_amount" in sent:
        item.discount_amount = body.discount_amount
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


# ---- 용돈(장부) ----


def _children(db: Session, group_id: str) -> list[User]:
    return [m for m in group_repo.members(db, group_id) if m.role != "parent"]


def _child(db: Session, group_id: str, child_id: str) -> User:
    child = next((c for c in _children(db, group_id) if c.id == child_id), None)
    if child is None:
        raise not_found("자녀")
    return child


def _can_manage_allowance(db: Session, group_id: str, user: User) -> bool:
    """주기 설정·지급·취소는 부모 역할이거나 그룹을 만든 사람만 한다."""
    return user.role == "parent" or group_repo.get_group(db, group_id).owner_id == user.id


def _ensure_manage_allowance(db: Session, group_id: str, user: User) -> None:
    if not _can_manage_allowance(db, group_id, user):
        raise ApiError(403, "not_allowance_manager", "부모님이나 그룹을 만든 사람만 할 수 있어요")


def _credit(
    child_id: str, group_id: str, plan: AllowancePlan, due: str, source: str, by: str | None
) -> AllowanceEntry:
    return AllowanceEntry(
        id=uuid.uuid4().hex[:12],
        group_id=group_id,
        child_id=child_id,
        kind="credit",
        amount=plan.amount,
        memo="정기 용돈",
        date=due,
        source=source,
        plan_due_date=due,
        created_by=by,
    )


def _due_list(plan: AllowancePlan, today: date) -> list[str]:
    start = date.fromisoformat(plan.start_date)
    return [d.isoformat() for d in allowance.due_dates(plan.cycle, plan.day, start, today)]


def _post_auto(db: Session, group_id: str, plan: AllowancePlan, today: date) -> None:
    """자동 방식: 지급일이 지난 분을 장부에 입금으로 기록한다. 서버에 정해진 시간에 도는 작업이 없어서
    화면을 열 때 기록하며, 같은 지급일은 한 번만 기록된다(unique)."""
    if plan.mode != "auto":
        return
    with seed_lock(db, f"allowance:{plan.child_id}"):  # 동시에 열어도 둘 다 기록하지 않게 잠근다
        done = repo.posted_due_dates(db, plan.child_id)
        new = [d for d in _due_list(plan, today) if d not in done]
        if not new:
            return
        try:
            repo.save_all(
                db, [_credit(plan.child_id, group_id, plan, d, "plan_auto", None) for d in new]
            )
        except IntegrityError:  # 다른 요청이 먼저 기록함
            db.rollback()


def _by_name(e: AllowanceEntry, names: dict[str, str]) -> str:
    """기록한 사람. 자동 지급은 "자동 지급", 이전 월 예산 방식에서 옮겨 온 줄은 "이전 기록"."""
    if e.created_by:
        return names.get(e.created_by, "")
    return "자동 지급" if e.source == "plan_auto" else "이전 기록"


def _entries_out(entries: list[AllowanceEntry], names: dict[str, str]):
    """오래된 순 목록으로 잔액을 차례로 계산해, (현재 잔액, 최신순 목록)을 돌려준다."""
    balance = 0
    out = []
    for e in entries:
        voided = e.voided_at is not None
        if not voided:
            balance += e.amount if e.kind == "credit" else -e.amount
        out.append(
            AllowanceEntryOut(
                id=e.id,
                kind=e.kind,
                amount=e.amount,
                memo=e.memo,
                date=e.date,
                source=e.source,
                by_name=_by_name(e, names),
                voided=voided,
                balance_after=None if voided else balance,
            )
        )
    return balance, list(reversed(out))


def _months(live: list[AllowanceEntry], today: date) -> list[AllowanceMonth]:
    """최근 6개월(이번 달 포함, 최신 달부터)의 받은 돈·쓴 돈. 취소한 줄은 이미 빠져 있다."""
    keys = []
    year, month = today.year, today.month
    for _ in range(6):
        keys.append(f"{year}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    totals = {k: [0, 0] for k in keys}
    for e in live:
        bucket = totals.get(e.date[:7])
        if bucket is not None:
            bucket[0 if e.kind == "credit" else 1] += e.amount
    return [AllowanceMonth(month=k, credit=totals[k][0], use=totals[k][1]) for k in keys]


def _request_out(r: AllowanceRequest, names: dict[str, str]) -> AllowanceRequestOut:
    return AllowanceRequestOut(
        id=r.id,
        amount=r.amount,
        memo=r.memo,
        status=r.status,
        created_at=r.created_at,
        decided_by_name=names.get(r.decided_by, "") if r.decided_by else "",
        decided_at=r.decided_at,
        approved_amount=r.approved_amount,
        decision_note=r.decision_note,
    )


def _requests_out(
    db: Session, group_id: str, child_id: str, names: dict[str, str]
) -> list[AllowanceRequestOut]:
    """대기 중인 요청(오래된 순) 다음에 최근 처리한 요청(최신순, 최대 10건)."""
    rows = repo.list_requests(db, group_id, child_id)
    waiting = [r for r in reversed(rows) if r.status == "pending"]
    done = [r for r in rows if r.status != "pending"][:10]
    return [_request_out(r, names) for r in [*waiting, *done]]


def _allowance_out(
    db: Session, group_id: str, user: User, child: User, names: dict[str, str], today: date
) -> AllowanceOut:
    plan = repo.get_plan(db, group_id, child.id)
    if plan is not None:
        _post_auto(db, group_id, plan, today)
    entries = repo.list_entries(db, group_id, child.id)
    balance, rows = _entries_out(entries, names)
    live = [e for e in entries if e.voided_at is None]
    can_manage = _can_manage_allowance(db, group_id, user)
    pending: list[AllowancePending] = []
    plan_out = None
    if plan is not None:
        if plan.mode == "remind" and can_manage:  # 지급 알림은 지급할 수 있는 사람에게만 보인다
            done = repo.posted_due_dates(db, child.id)
            pending = [
                AllowancePending(due_date=d, amount=plan.amount)
                for d in _due_list(plan, today)
                if d not in done
            ]
        plan_out = AllowancePlanOut(
            cycle=plan.cycle,
            day=plan.day,
            amount=plan.amount,
            mode=plan.mode,
            start_date=plan.start_date,
            next_due=allowance.next_due(plan.cycle, plan.day, today).isoformat(),
        )
    return AllowanceOut(
        child_id=child.id,
        name=child.name,
        balance=balance,
        total_credit=sum(e.amount for e in live if e.kind == "credit"),
        total_use=sum(e.amount for e in live if e.kind == "use"),
        plan=plan_out,
        pending=pending,
        entries=rows[:100],
        can_manage=can_manage,
        can_record_use=can_manage or user.id == child.id,
        can_request=user.id == child.id,
        requests=_requests_out(db, group_id, child.id, names),
        months=_months(live, today),
    )


def _today() -> date:
    return date.fromisoformat(today_kst())


def _names(db: Session, group_id: str) -> dict[str, str]:
    return {m.id: m.name for m in group_repo.members(db, group_id)}


def list_allowances(db: Session, group_id: str, user: User) -> list[AllowanceOut]:
    names, today = _names(db, group_id), _today()
    return [_allowance_out(db, group_id, user, c, names, today) for c in _children(db, group_id)]


def _one(db: Session, group_id: str, user: User, child_id: str) -> AllowanceOut:
    child = _child(db, group_id, child_id)
    return _allowance_out(db, group_id, user, child, _names(db, group_id), _today())


def set_plan(
    db: Session, group_id: str, user: User, child_id: str, body: AllowancePlanIn
) -> AllowanceOut:
    _child(db, group_id, child_id)
    _ensure_manage_allowance(db, group_id, user)
    if body.cycle == "weekly" and not 0 <= body.day <= 6:
        raise bad_request("invalid_day", "요일은 월(0)부터 일(6)까지예요")
    if body.cycle == "monthly" and not 1 <= body.day <= 31:
        raise bad_request("invalid_day", "지급일은 1~31 사이여야 해요")
    plan = repo.get_plan(db, group_id, child_id)
    if plan is None:
        plan = AllowancePlan(id=uuid.uuid4().hex[:12], group_id=group_id, child_id=child_id)
    # 설정을 바꾸면 오늘부터 새 주기로 센다(이미 기록한 입금은 그대로, 지난 날짜를 소급해 만들지 않는다)
    plan.cycle, plan.day, plan.amount, plan.mode = body.cycle, body.day, body.amount, body.mode
    plan.start_date = today_kst()
    repo.save(db, plan)
    return _one(db, group_id, user, child_id)


def delete_plan(db: Session, group_id: str, user: User, child_id: str) -> AllowanceOut:
    _child(db, group_id, child_id)
    _ensure_manage_allowance(db, group_id, user)
    plan = repo.get_plan(db, group_id, child_id)
    if plan is None:
        raise not_found("용돈 주기")
    repo.delete(db, plan)  # 장부 내역은 그대로 남는다
    return _one(db, group_id, user, child_id)


def _entry_date(day: date | None) -> str:
    today = today_kst()
    value = day.isoformat() if day else today
    if value > today:
        raise bad_request("future_date", "오늘 이후 날짜는 기록할 수 없어요")
    return value


def _balance(db: Session, group_id: str, child_id: str) -> int:
    return _entries_out(repo.list_entries(db, group_id, child_id), {})[0]


def add_credit(
    db: Session, group_id: str, user: User, child_id: str, body: AllowanceMoneyIn
) -> AllowanceOut:
    """수동 지급(부모가 직접 입금으로 기록)."""
    _child(db, group_id, child_id)
    _ensure_manage_allowance(db, group_id, user)
    repo.save(
        db,
        AllowanceEntry(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            child_id=child_id,
            kind="credit",
            amount=body.amount,
            memo=body.memo.strip() or "용돈",
            date=_entry_date(body.date),
            source="manual",
            created_by=user.id,
        ),
    )
    return _one(db, group_id, user, child_id)


def pay_due(
    db: Session, group_id: str, user: User, child_id: str, body: AllowancePayIn
) -> AllowanceOut:
    """리마인드 방식: "지급했어요" 를 누르면 그 지급일의 입금을 장부에 기록한다."""
    _child(db, group_id, child_id)
    _ensure_manage_allowance(db, group_id, user)
    plan = repo.get_plan(db, group_id, child_id)
    if plan is None or plan.mode != "remind":
        raise bad_request("not_remind", "리마인드 방식 주기가 아니에요")
    due = body.due_date.isoformat()
    if due not in _due_list(plan, _today()):
        raise bad_request("invalid_due", "지급 알림이 있는 날짜가 아니에요")
    try:
        repo.save(db, _credit(child_id, group_id, plan, due, "plan_remind", user.id))
    except IntegrityError:
        db.rollback()
        raise bad_request("already_paid", "이미 지급 기록이 있어요") from None
    return _one(db, group_id, user, child_id)


def add_use(
    db: Session, group_id: str, user: User, child_id: str, body: AllowanceMoneyIn
) -> AllowanceOut:
    """사용 내역 기록. 본인이나 관리 권한자만, 잔액보다 큰 사용은 저장하지 않는다."""
    _child(db, group_id, child_id)
    if user.id != child_id and not _can_manage_allowance(db, group_id, user):
        raise ApiError(403, "not_allowed", "본인이나 부모님만 사용 내역을 기록할 수 있어요")
    day = _entry_date(body.date)
    with seed_lock(db, f"allowance:{child_id}"):  # 동시에 두 번 써서 잔액을 넘기지 않게 잠근다
        balance = _balance(db, group_id, child_id)
        if body.amount > balance:
            raise bad_request("over_balance", f"잔액({balance:,}원)보다 큰 사용은 저장할 수 없어요")
        repo.save(
            db,
            AllowanceEntry(
                id=uuid.uuid4().hex[:12],
                group_id=group_id,
                child_id=child_id,
                kind="use",
                amount=body.amount,
                memo=body.memo.strip(),
                date=day,
                source="manual",
                created_by=user.id,
            ),
        )
    return _one(db, group_id, user, child_id)


def request_allowance(
    db: Session, group_id: str, user: User, child_id: str, body: AllowanceRequestIn
) -> AllowanceOut:
    """자녀 본인이 용돈을 요청한다(부모가 대신 요청하지 않는다 — 부모는 바로 지급 기록을 쓴다)."""
    _child(db, group_id, child_id)
    if user.id != child_id:
        raise ApiError(403, "not_allowed", "본인의 용돈만 요청할 수 있어요")
    with seed_lock(db, f"allowance-request:{child_id}"):
        waiting = [r for r in repo.list_requests(db, group_id, child_id) if r.status == "pending"]
        if len(waiting) >= repo.MAX_PENDING_REQUESTS:
            raise bad_request(
                "too_many_requests",
                f"대기 중인 요청은 {repo.MAX_PENDING_REQUESTS}건까지예요. 처리된 뒤에 다시 요청해 주세요",
            )
        repo.save(
            db,
            AllowanceRequest(
                id=uuid.uuid4().hex[:12],
                group_id=group_id,
                child_id=child_id,
                amount=body.amount,
                memo=body.memo.strip(),
            ),
        )
    managers = [
        m.id for m in group_repo.members(db, group_id) if _can_manage_allowance(db, group_id, m)
    ]
    _notify_billing(
        db,
        group_id,
        user.id,
        "allowance_requested",
        "용돈 요청이 도착했어요",
        managers,
        "allowance",
        child_id,
    )
    return _one(db, group_id, user, child_id)


def _pending_request(
    db: Session, group_id: str, child_id: str, request_id: str
) -> AllowanceRequest:
    req = repo.get_request(db, group_id, child_id, request_id)
    if req is None:
        raise not_found("용돈 요청")
    if req.status != "pending":
        raise bad_request("not_pending", "이미 처리된 요청이에요")
    return req


def _notify_decided(db: Session, group_id: str, user: User, child_id: str) -> None:
    """용돈 요청이 처리되면 자녀에게 알린다. 승인·거절 여부와 금액은 문구에 담지 않는다(알림을 열어 확인한다)."""
    _notify_billing(
        db,
        group_id,
        user.id,
        "allowance_decided",
        "용돈 요청이 처리됐어요",
        [child_id],
        "allowance",
        child_id,
    )


def approve_request(
    db: Session,
    group_id: str,
    user: User,
    child_id: str,
    request_id: str,
    body: AllowanceApproveIn,
) -> AllowanceOut:
    """승인하면 장부에 입금 한 줄이 생긴다(금액을 바꿔 승인할 수 있다). 한 요청은 한 번만 승인된다."""
    _child(db, group_id, child_id)
    _ensure_manage_allowance(db, group_id, user)
    with seed_lock(db, f"allowance-request:{child_id}"):
        req = _pending_request(db, group_id, child_id, request_id)
        amount = body.amount or req.amount
        entry = AllowanceEntry(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            child_id=child_id,
            kind="credit",
            amount=amount,
            memo=(f"용돈 요청: {req.memo}" if req.memo else "용돈 요청")[:120],
            date=today_kst(),
            source="request",
            created_by=user.id,
        )
        req.status, req.decided_by, req.decided_at = "approved", user.id, datetime.now(UTC)
        req.approved_amount, req.decision_note, req.entry_id = amount, body.note.strip(), entry.id
        repo.save_all(db, [entry, req])  # 입금과 승인 표시를 한 번에 저장한다
    _notify_decided(db, group_id, user, child_id)
    return _one(db, group_id, user, child_id)


def reject_request(
    db: Session,
    group_id: str,
    user: User,
    child_id: str,
    request_id: str,
    body: AllowanceRejectIn,
) -> AllowanceOut:
    _child(db, group_id, child_id)
    _ensure_manage_allowance(db, group_id, user)
    with seed_lock(db, f"allowance-request:{child_id}"):
        req = _pending_request(db, group_id, child_id, request_id)
        req.status, req.decided_by, req.decided_at = "rejected", user.id, datetime.now(UTC)
        req.decision_note = body.note.strip()
        repo.save(db, req)
    _notify_decided(db, group_id, user, child_id)
    return _one(db, group_id, user, child_id)


def cancel_request(
    db: Session, group_id: str, user: User, child_id: str, request_id: str
) -> AllowanceOut:
    """자녀가 자기 대기 요청을 취소한다."""
    _child(db, group_id, child_id)
    if user.id != child_id:
        raise ApiError(403, "not_allowed", "본인의 요청만 취소할 수 있어요")
    with seed_lock(db, f"allowance-request:{child_id}"):
        req = _pending_request(db, group_id, child_id, request_id)
        req.status, req.decided_by, req.decided_at = "cancelled", user.id, datetime.now(UTC)
        repo.save(db, req)
    return _one(db, group_id, user, child_id)


def void_entry(
    db: Session, group_id: str, user: User, child_id: str, entry_id: str
) -> AllowanceOut:
    """장부 줄 취소(지우지 않고 취소 표시). 입금을 취소해 잔액이 음수가 되면 거절한다."""
    _child(db, group_id, child_id)
    entry = repo.get_entry(db, group_id, child_id, entry_id)
    if entry is None:
        raise not_found("장부 내역")
    if user.id != entry.created_by and not _can_manage_allowance(db, group_id, user):
        raise ApiError(403, "not_allowed", "기록한 사람이나 부모님만 취소할 수 있어요")
    if entry.voided_at is not None:
        raise bad_request("already_voided", "이미 취소한 내역이에요")
    with seed_lock(db, f"allowance:{child_id}"):
        if entry.kind == "credit" and _balance(db, group_id, child_id) - entry.amount < 0:
            raise bad_request("balance_negative", "이 입금을 취소하면 잔액이 모자라져요")
        entry.voided_at = datetime.now(UTC)
        repo.save(db, entry)
    return _one(db, group_id, user, child_id)
