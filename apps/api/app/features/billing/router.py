from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.config import settings
from app.shared.db import get_db
from app.shared.errors import ApiError
from app.shared.llm import agent_chat as agent_chat_service
from app.shared.llm.schemas import (
    AgentChatIn,
    AgentChatOut,
    AgentConfirmIn,
    AgentConfirmOut,
)

from . import agent, service
from .schemas import (
    AllowanceApproveIn,
    AllowanceMoneyIn,
    AllowanceOut,
    AllowancePayIn,
    AllowancePlanIn,
    AllowanceRejectIn,
    AllowanceRequestIn,
    ExpenseCreate,
    ExpenseOut,
    ManagerOut,
    ManagerSet,
    MinorsSet,
    MonthlyGenerate,
    MonthlyPlan,
    MonthlyResult,
    PaymentCreate,
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
    UpcomingPayments,
)

router = APIRouter(prefix="/billing", tags=["billing"])


def require_subscription_api() -> None:
    """구독·통신비 서버 API 스위치(SUBSCRIPTION_API_ENABLED). 닫혀 있으면 /billing/subscriptions* 요청을 403 subscription_disabled 로 막는다."""
    if not settings.subscription_api_enabled:
        raise ApiError(403, "subscription_disabled", "구독 기능은 지금 사용할 수 없어요")


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[ExpenseOut]:
    return service.list_expenses(db, group_id, service.check_month(month or service.this_month()))


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(
    body: ExpenseCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    return service.create(db, group_id, user.id, body)


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Response:
    """소프트 삭제: 행은 남기고 `deleted_at` 만 채운다."""
    service.delete_expense(db, group_id, expense_id)
    return Response(status_code=204)


@router.get("/summary", response_model=Summary)
def month_summary(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Summary:
    return service.summary(db, group_id, service.check_month(month or service.this_month()))


@router.get("/settlement", response_model=Settlement)
def get_settlement(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Settlement:
    return service.settlement(db, group_id, service.check_month(month or service.this_month()))


@router.get("/settlement/tags", response_model=list[SettleTagOut])
def settle_tags(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> list[SettleTagOut]:
    """정산 대상 고정 태그와 태그별 기본 나눌 사람."""
    return service.settle_tags(db, group_id)


@router.post("/settlement/tag", response_model=Settlement)
def settle(
    body: SettleRequest,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Settlement:
    """'정산하기': 고른 지출에 대상 태그와 나눌 사람을 정하고 바뀐 정산 결과를 돌려준다."""
    return service.settle(db, group_id, user.id, body)


@router.get("/settlement/manager", response_model=ManagerOut)
def get_manager(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ManagerOut:
    """정산 담당자(월말 알림을 받는 사람). 지정하지 않았으면 그룹을 만든 사람."""
    return service.get_manager(db, group_id, user)


@router.put("/settlement/manager", response_model=ManagerOut)
def set_manager(
    body: ManagerSet,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ManagerOut:
    return service.set_manager(db, group_id, user, body.user_id)


@router.put("/settlement/minors", response_model=ManagerOut)
def set_minors(
    body: MinorsSet,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ManagerOut:
    """미성년 자녀 표시(정산 담당자·그룹을 만든 사람만). 있으면 '자녀 대상' 정산은 부모님이 부담한다."""
    return service.set_minors(db, group_id, user, body.user_ids)


@router.get("/settlement/reminder", response_model=Reminder)
def settlement_reminder(
    on: str | None = None,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Reminder:
    """월말 정산 알림. 정산 담당자에게만 show=true 가 내려간다. `on` 은 화면 테스트용 날짜(YYYY-MM-DD)."""
    return service.reminder(db, group_id, user, on)


@router.post("/settlement/payments", response_model=Settlement, status_code=201)
def mark_paid(
    body: PaymentCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Settlement:
    """송금 목록에 있는 송금 하나를 '송금 완료'로 표시한다."""
    return service.mark_paid(db, group_id, body, user.id)


@router.delete("/settlement/payments/{payment_id}", response_model=Settlement)
def undo_paid(
    payment_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Settlement:
    return service.undo_paid(db, group_id, payment_id)


@router.get(
    "/subscriptions",
    dependencies=[Depends(require_subscription_api)],
    response_model=SubscriptionList,
)
def list_subscriptions(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> SubscriptionList:
    return service.list_subscriptions(db, group_id)


@router.get(
    "/subscriptions/catalog",
    dependencies=[Depends(require_subscription_api)],
    response_model=SubscriptionCatalog,
)
def subscription_catalog(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> SubscriptionCatalog:
    """고를 수 있는 OTT·통신비 서비스 목록. 골라서 `POST /subscriptions` 로 추가한다."""
    return service.subscription_catalog(db, group_id)


@router.post(
    "/subscriptions",
    dependencies=[Depends(require_subscription_api)],
    response_model=SubscriptionOut,
    status_code=201,
)
def create_subscription(
    body: SubscriptionCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    """OTT·통신비 항목 추가. 월 금액·결제일은 사용자가 입력한 값만 저장한다. 결제한 사람을 안 보내면 등록한 사람이다."""
    return service.create_subscription(db, group_id, user, body)


@router.get(
    "/subscriptions/upcoming",
    dependencies=[Depends(require_subscription_api)],
    response_model=UpcomingPayments,
)
def upcoming_payments(
    on: str | None = None,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> UpcomingPayments:
    """결제일이 3일 안으로 다가온 구독(결제한 사람에게만). `on=YYYY-MM-DD`는 화면 테스트용 오늘 날짜."""
    return service.upcoming_payments(db, group_id, user, on)


@router.get(
    "/subscriptions/monthly",
    dependencies=[Depends(require_subscription_api)],
    response_model=MonthlyPlan,
)
def monthly_plan(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MonthlyPlan:
    """그 달 구독료 지출로 만들 수 있는 항목(만들 수 있음 / 이미 만듦 / 금액 없음 / 결제한 사람 없음)."""
    return service.monthly_plan(db, group_id, month or service.this_month())


@router.post(
    "/subscriptions/monthly",
    dependencies=[Depends(require_subscription_api)],
    response_model=MonthlyResult,
    status_code=201,
)
def generate_monthly(
    body: MonthlyGenerate,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MonthlyResult:
    """'이번 달 구독료 지출 만들기': 금액이 있는 항목만 미정산 지출로 만든다. 같은 달에 다시 불러도 중복으로 만들지 않는다."""
    return service.generate_monthly(db, group_id, body.month)


@router.patch(
    "/subscriptions/{item_id}",
    dependencies=[Depends(require_subscription_api)],
    response_model=SubscriptionOut,
)
def update_subscription(
    item_id: str,
    body: SubscriptionPatch,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    """상태·이름·통신사·월 금액·결제일 중 보낸 것만 바꾼다."""
    return service.update_subscription(db, group_id, item_id, body)


@router.delete(
    "/subscriptions/{item_id}", dependencies=[Depends(require_subscription_api)], status_code=204
)
def delete_subscription(
    item_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Response:
    """소프트 삭제: 항목은 목록에서 빠지고 행은 남는다."""
    service.delete_subscription(db, group_id, item_id)
    return Response(status_code=204)


@router.get("/allowances", response_model=list[AllowanceOut])
def list_allowances(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[AllowanceOut]:
    """자녀별 용돈 장부(잔액·내역·주기). 자동 방식은 지급일이 지난 분을 입금으로 기록한 뒤 돌려준다."""
    return service.list_allowances(db, group_id, user)


@router.put("/allowances/{child_id}/plan", response_model=AllowanceOut)
def set_plan(
    child_id: str,
    body: AllowancePlanIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """고정 용돈 주기 설정(부모·그룹을 만든 사람). 자동 지급 또는 리마인드."""
    return service.set_plan(db, group_id, user, child_id, body)


@router.delete("/allowances/{child_id}/plan", response_model=AllowanceOut)
def delete_plan(
    child_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """주기를 없앤다. 장부 내역은 그대로 남는다."""
    return service.delete_plan(db, group_id, user, child_id)


@router.post("/allowances/{child_id}/plan/pay", response_model=AllowanceOut, status_code=201)
def pay_due(
    child_id: str,
    body: AllowancePayIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """리마인드 방식에서 "지급했어요": 그 지급일의 입금을 장부에 기록한다."""
    return service.pay_due(db, group_id, user, child_id, body)


@router.post("/allowances/{child_id}/credits", response_model=AllowanceOut, status_code=201)
def add_credit(
    child_id: str,
    body: AllowanceMoneyIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """수동 지급 기록(부모·그룹을 만든 사람)."""
    return service.add_credit(db, group_id, user, child_id, body)


@router.post("/allowances/{child_id}/uses", response_model=AllowanceOut, status_code=201)
def add_use(
    child_id: str,
    body: AllowanceMoneyIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """사용 내역 기록(본인 또는 부모). 잔액보다 큰 사용은 거절한다."""
    return service.add_use(db, group_id, user, child_id, body)


@router.post("/allowances/{child_id}/requests", response_model=AllowanceOut, status_code=201)
def request_allowance(
    child_id: str,
    body: AllowanceRequestIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """자녀 본인이 용돈을 요청한다(대기 5건까지)."""
    return service.request_allowance(db, group_id, user, child_id, body)


@router.post("/allowances/{child_id}/requests/{request_id}/approve", response_model=AllowanceOut)
def approve_request(
    child_id: str,
    request_id: str,
    body: AllowanceApproveIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """승인(부모·그룹을 만든 사람): 장부에 입금이 기록된다. 금액을 바꿔 승인할 수 있다."""
    return service.approve_request(db, group_id, user, child_id, request_id, body)


@router.post("/allowances/{child_id}/requests/{request_id}/reject", response_model=AllowanceOut)
def reject_request(
    child_id: str,
    request_id: str,
    body: AllowanceRejectIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    return service.reject_request(db, group_id, user, child_id, request_id, body)


@router.delete("/allowances/{child_id}/requests/{request_id}", response_model=AllowanceOut)
def cancel_request(
    child_id: str,
    request_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """자녀가 자기 대기 요청을 취소한다."""
    return service.cancel_request(db, group_id, user, child_id, request_id)


@router.delete("/allowances/{child_id}/entries/{entry_id}", response_model=AllowanceOut)
def void_entry(
    child_id: str,
    entry_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    """장부 내역 취소(지우지 않고 취소 표시)."""
    return service.void_entry(db, group_id, user, child_id, entry_id)


@router.post("/agent/chat", response_model=AgentChatOut)
def agent_chat(
    body: AgentChatIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AgentChatOut:
    """정산(가계) 에이전트와 직접 대화한다(메인 에이전트를 거치지 않는다). 조회는 바로 답하고, 쓰기는 응답의 proposals 로 제안만 한다(agent/confirm 으로 확인해야 실행)."""
    return agent_chat_service.chat(db, group_id, user, body, agent.ask)


@router.post("/agent/confirm", response_model=AgentConfirmOut)
def agent_confirm(
    body: AgentConfirmIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AgentConfirmOut:
    """에이전트가 제안한 가계 쓰기를 사용자가 확인했을 때 실행한다. 토큰은 제안받은 본인·가족·탭에서 10분 안에 한 번만 쓸 수 있다."""
    return agent_chat_service.confirm(db, group_id, user, body, "billing", agent.execute)
