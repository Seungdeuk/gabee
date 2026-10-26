import { apiFetch } from "@/shared/api/client";

/**
 * 가계 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /billing/* 를 따른다.
 * @typedef {{ user_id: string, name: string, paid: number, share: number, balance: number, remaining: number }} Balance
 * @typedef {{ from_user_id: string, from_name: string, to_user_id: string, to_name: string, amount: number }} Transfer
 * @typedef {Transfer & { id: string }} Payment
 * @typedef {{ month: string, balances: Balance[], transfers: Transfer[], completed: Payment[], unsettled_count: number, unsettled_total: number }} Settlement
 * @typedef {{ id: string, title: string, amount: number, date: string, category: string, subscription_id: string | null, paid_by: string, paid_by_name: string, split_among: string[], target_tag: "parents" | "children" | "all" | "custom", settled: boolean }} Expense
 * @typedef {{ id: string, kind: "ott" | "telecom", name: string, status: "check" | "available" | "active", carrier: "skt" | "kt" | "lgu" | "mvno" | "other" | null, monthly_fee: number | null, discount_amount: number | null, list_price: number | null, billing_day: number | null, payer_id: string | null, payer_name: string, split_among: string[] }} Subscription
 * @typedef {{ id: string, name: string, kind: "ott" | "telecom", amount: number | null, date: string, payer_name: string, split_count: number, state: "ready" | "created" | "no_fee" | "no_payer" }} MonthlyItem
 * @typedef {{ month: string, items: MonthlyItem[], ready_count: number, ready_total: number }} MonthlyPlan
 * @typedef {{ cycle: "weekly" | "monthly", day: number, amount: number, mode: "auto" | "remind", start_date: string, next_due: string }} AllowancePlan
 * @typedef {{ id: string, kind: "credit" | "use", amount: number, memo: string, date: string, source: "manual" | "plan_auto" | "plan_remind" | "request", by_name: string, voided: boolean, balance_after: number | null }} AllowanceEntry
 * @typedef {{ id: string, amount: number, memo: string, status: "pending" | "approved" | "rejected" | "cancelled", created_at: string, decided_by_name: string, decided_at: string | null, approved_amount: number | null, decision_note: string }} AllowanceRequest
 * @typedef {{ child_id: string, name: string, balance: number, total_credit: number, total_use: number, plan: AllowancePlan | null, pending: { due_date: string, amount: number }[], entries: AllowanceEntry[], can_manage: boolean, can_record_use: boolean, can_request: boolean, requests: AllowanceRequest[], months: { month: string, credit: number, use: number }[] }} Allowance
 */

const monthQuery = (month) => `?month=${encodeURIComponent(month)}`;

/** @param {string} month YYYY-MM @returns {Promise<Settlement>} */
export const getSettlement = (month) => apiFetch(`/billing/settlement${monthQuery(month)}`);

/**
 * 송금 목록의 송금 하나를 '송금 완료'로 표시한다. 바뀐 정산 결과를 돌려준다.
 * @param {string} month
 * @param {Transfer} transfer
 * @returns {Promise<Settlement>}
 */
export const markPaid = (month, transfer) =>
  apiFetch("/billing/settlement/payments", {
    method: "POST",
    body: {
      month,
      from_user_id: transfer.from_user_id,
      to_user_id: transfer.to_user_id,
      amount: transfer.amount,
    },
  });

/** @param {string} paymentId @returns {Promise<Settlement>} */
export const undoPaid = (paymentId) => apiFetch(`/billing/settlement/payments/${paymentId}`, { method: "DELETE" });

/** @param {string} month @returns {Promise<Expense[]>} */
export const getExpenses = (month) => apiFetch(`/billing/expenses${monthQuery(month)}`);

/**
 * @param {{ title: string, amount: number, date: string }} body 낸 사람은 서버가 로그인한 사용자로 정한다
 * @returns {Promise<Expense>}
 */
export const createExpense = (body) => apiFetch("/billing/expenses", { method: "POST", body });

/** 소프트 삭제. @param {string} id */
export const deleteExpense = (id) => apiFetch(`/billing/expenses/${id}`, { method: "DELETE" });

/** 가족 구성원(낸 사람·나눌 사람 고르기용). @returns {Promise<{ id: string, name: string, role: string }[]>} */
export async function getMembers() {
  const group = await apiFetch("/family-group/groups/me");
  return group.members;
}

/** @returns {Promise<{ notice: string, items: Subscription[], monthly_total: number, discount_total: number }>} 월 합계는 월 청구 금액의 합(할인이 이미 빠진 값), 할인 합계는 직접 입력한 값의 합 */
export const getSubscriptions = () => apiFetch("/billing/subscriptions");

/** @returns {Promise<{ items: { kind: "ott" | "telecom", name: string, added: boolean }[] }>} 고를 수 있는 서비스 목록(이미 추가한 것은 added) */
export const getSubscriptionCatalog = () => apiFetch("/billing/subscriptions/catalog");

/**
 * OTT·통신비 항목 추가. 월 금액·결제일은 사용자가 입력한 값만 저장한다(할인 금액은 계산하지 않는다).
 * @param {{ kind: "ott" | "telecom", name: string, carrier?: Subscription["carrier"], monthly_fee?: number | null, discount_amount?: number | null, billing_day?: number | null, payer_id?: string | null, split_among?: string[] }} body 결제한 사람을 안 보내면 등록한 사람, 나눌 사람이 비어 있으면 가족 전체
 * @returns {Promise<Subscription>}
 */
export const createSubscription = (body) => apiFetch("/billing/subscriptions", { method: "POST", body });

/**
 * 보낸 필드만 바꾼다(status, name, carrier, monthly_fee, billing_day). 금액·결제일·통신사는 null 을 보내면 지운다.
 * @param {string} id
 * @param {Partial<Pick<Subscription, "status" | "name" | "carrier" | "monthly_fee" | "discount_amount" | "billing_day" | "payer_id" | "split_among">>} patch
 * @returns {Promise<Subscription>}
 */
export const updateSubscription = (id, patch) => apiFetch(`/billing/subscriptions/${id}`, { method: "PATCH", body: patch });

/** 그 달에 구독료 지출로 만들 수 있는 항목. @param {string} month YYYY-MM @returns {Promise<MonthlyPlan>} */
export const getMonthlyPlan = (month) => apiFetch(`/billing/subscriptions/monthly?month=${encodeURIComponent(month)}`);

/**
 * '이번 달 구독료 지출 만들기': 금액이 있는 항목만 미정산 지출로 만든다. 같은 달에 다시 불러도 중복으로 만들지 않는다.
 * @param {string} month YYYY-MM
 * @returns {Promise<{ created: Expense[], plan: MonthlyPlan }>}
 */
export const generateMonthly = (month) => apiFetch("/billing/subscriptions/monthly", { method: "POST", body: { month } });

/** 내 사용자 id(결제한 사람 기본값). @returns {Promise<string>} */
export const getMyId = async () => (await apiFetch("/family-group/me")).id;

/** 소프트 삭제. @param {string} id */
export const deleteSubscription = (id) => apiFetch(`/billing/subscriptions/${id}`, { method: "DELETE" });

/**
 * 자녀별 용돈 장부(잔액·내역·주기). 자동 방식은 지급일이 지난 분을 서버가 입금으로 기록한 뒤 돌려준다.
 * 은행·계좌와 연결하지 않는 앱 안 장부다.
 * @returns {Promise<Allowance[]>}
 */
export const getAllowances = () => apiFetch("/billing/allowances");

/**
 * 고정 용돈 주기 설정(가족 소유자·관리자. 관리자는 본인 용돈 불가). weekly 의 day 는 0(월)~6(일), monthly 는 1~31.
 * @param {string} childId
 * @param {{ cycle: "weekly" | "monthly", day: number, amount: number, mode: "auto" | "remind" }} body
 * @returns {Promise<Allowance>}
 */
export const setAllowancePlan = (childId, body) => apiFetch(`/billing/allowances/${childId}/plan`, { method: "PUT", body });

/** 주기를 없앤다(장부 내역은 남는다). @param {string} childId @returns {Promise<Allowance>} */
export const deleteAllowancePlan = (childId) => apiFetch(`/billing/allowances/${childId}/plan`, { method: "DELETE" });

/** 리마인드 방식의 "지급했어요". @param {string} childId @param {string} dueDate YYYY-MM-DD @returns {Promise<Allowance>} */
export const payAllowanceDue = (childId, dueDate) =>
  apiFetch(`/billing/allowances/${childId}/plan/pay`, { method: "POST", body: { due_date: dueDate } });

/**
 * 수동 지급 기록(가족 소유자·관리자. 관리자는 본인 용돈 불가).
 * @param {string} childId
 * @param {{ amount: number, memo?: string }} body
 * @returns {Promise<Allowance>}
 */
export const addAllowanceCredit = (childId, body) => apiFetch(`/billing/allowances/${childId}/credits`, { method: "POST", body });

/**
 * 용돈 사용 기록(본인 또는 가족 소유자·관리자). 잔액보다 크면 서버가 over_balance 오류로 거절한다.
 * @param {string} childId
 * @param {{ amount: number, memo?: string }} body
 * @returns {Promise<Allowance>}
 */
export const addAllowanceUse = (childId, body) => apiFetch(`/billing/allowances/${childId}/uses`, { method: "POST", body });

/**
 * 용돈 요청(자녀 본인만, 대기 5건까지).
 * @param {string} childId
 * @param {{ amount: number, memo?: string }} body
 * @returns {Promise<Allowance>}
 */
export const requestAllowance = (childId, body) => apiFetch(`/billing/allowances/${childId}/requests`, { method: "POST", body });

/**
 * 요청 승인(가족 소유자·관리자. 관리자는 본인 용돈 불가): 장부에 입금이 기록된다. amount 를 안 보내면 요청한 금액이다.
 * @param {string} childId @param {string} requestId @param {{ amount?: number, note?: string }} body
 * @returns {Promise<Allowance>}
 */
export const approveAllowanceRequest = (childId, requestId, body) =>
  apiFetch(`/billing/allowances/${childId}/requests/${requestId}/approve`, { method: "POST", body });

/** 요청 거절(가족 소유자·관리자. 관리자는 본인 용돈 불가). @param {string} childId @param {string} requestId @param {{ note?: string }} body @returns {Promise<Allowance>} */
export const rejectAllowanceRequest = (childId, requestId, body) =>
  apiFetch(`/billing/allowances/${childId}/requests/${requestId}/reject`, { method: "POST", body });

/** 자기 대기 요청 취소(자녀 본인). @param {string} childId @param {string} requestId @returns {Promise<Allowance>} */
export const cancelAllowanceRequest = (childId, requestId) =>
  apiFetch(`/billing/allowances/${childId}/requests/${requestId}`, { method: "DELETE" });

/** 장부 내역 취소(지우지 않고 취소 표시). @param {string} childId @param {string} entryId @returns {Promise<Allowance>} */
export const voidAllowanceEntry = (childId, entryId) =>
  apiFetch(`/billing/allowances/${childId}/entries/${entryId}`, { method: "DELETE" });

/**
 * 정산 대상 고정 태그와 태그별 기본 나눌 사람.
 * @returns {Promise<{ key: "parents" | "children" | "all", label: string, description: string, participants: string[] }[]>}
 */
export const getSettleTags = () => apiFetch("/billing/settlement/tags");

/**
 * '정산하기': 고른 지출에 대상 태그와 나눌 사람을 정한다. 직접 고르기는 tag 를 "custom" 으로 보내고 participants 를 함께 보낸다.
 * @param {{ month: string, expense_ids: string[], tag: "parents" | "children" | "all" | "custom", participants?: string[] }} body
 * @returns {Promise<Settlement>}
 */
export const settleExpenses = (body) => apiFetch("/billing/settlement/tag", { method: "POST", body });

/**
 * 정산 담당자(월말 알림을 받는 사람). 지정하지 않았으면 그룹을 만든 사람.
 * @returns {Promise<{ manager_id: string, manager_name: string, is_me: boolean, minor_ids: string[] }>}
 */
export const getManager = () => apiFetch("/billing/settlement/manager");

/** 담당자 변경: 지금 담당자나 그룹을 만든 사람만 할 수 있다. @param {string} userId */
export const setManager = (userId) => apiFetch("/billing/settlement/manager", { method: "PUT", body: { user_id: userId } });

/**
 * 미성년 자녀 표시(정산 담당자·그룹을 만든 사람만). 표시가 있으면 '자녀 대상' 정산은 부모님이 부담한다.
 * @param {string[]} userIds 미성년 자녀 id 들(부모 역할은 고를 수 없다)
 */
export const setMinors = (userIds) =>
  apiFetch("/billing/settlement/minors", { method: "PUT", body: { user_ids: userIds } });

// 개발용: 월말 알림을 확인할 때 오늘 날짜를 바꾼다(EXPO_PUBLIC_DEV_TODAY=YYYY-MM-DD). 비우면 실제 오늘.
const DEV_TODAY = process.env.EXPO_PUBLIC_DEV_TODAY ?? "";

/**
 * 월말 정산 알림. 정산 담당자에게만 show 가 true 다(월말 마지막 5일, 월초 5일은 지난 달이 밀렸을 때).
 * @returns {Promise<{ show: boolean, is_manager: boolean, manager_name: string, kind: "month_end" | "overdue" | null, month: string | null, unsettled_count: number, unsettled_total: number, days_left: number | null }>}
 */
export const getReminder = () => apiFetch(`/billing/settlement/reminder${DEV_TODAY ? `?on=${DEV_TODAY}` : ""}`);

/**
 * 구독 결제일 알림: 결제일이 3일 안(오늘 포함)으로 다가온 구독. 그 항목의 결제한 사람에게만 내려간다.
 * @returns {Promise<{ show: boolean, within_days: number, items: { id: string, kind: "ott" | "telecom", name: string, amount: number | null, due_date: string, days_left: number, expense_made: boolean }[] }>}
 */
export const getUpcomingPayments = () => apiFetch(`/billing/subscriptions/upcoming${DEV_TODAY ? `?on=${DEV_TODAY}` : ""}`);
