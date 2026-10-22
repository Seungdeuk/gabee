import { apiFetch } from "@/shared/api/client";

/**
 * 가계 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /billing/* 를 따른다.
 * @typedef {{ user_id: string, name: string, paid: number, share: number, balance: number, remaining: number }} Balance
 * @typedef {{ from_user_id: string, from_name: string, to_user_id: string, to_name: string, amount: number }} Transfer
 * @typedef {Transfer & { id: string }} Payment
 * @typedef {{ month: string, balances: Balance[], transfers: Transfer[], completed: Payment[] }} Settlement
 * @typedef {{ id: string, title: string, amount: number, date: string, category: string, paid_by: string, paid_by_name: string, split_among: string[] }} Expense
 * @typedef {{ id: string, kind: "ott" | "telecom", name: string, status: "check" | "available" | "active" }} Subscription
 * @typedef {{ id: string, amount: number, memo: string, date: string }} AllowanceUse
 * @typedef {{ child_id: string, name: string, month: string, budget: number | null, used: number, remaining: number, uses: AllowanceUse[] }} Allowance
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
 * @param {{ title: string, amount: number, date: string, paid_by: string, split_among: string[] }} body
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

/** @returns {Promise<{ notice: string, items: Subscription[] }>} */
export const getSubscriptions = () => apiFetch("/billing/subscriptions");

/** @param {string} id @param {Subscription["status"]} status @returns {Promise<Subscription>} */
export const setSubscriptionStatus = (id, status) =>
  apiFetch(`/billing/subscriptions/${id}`, { method: "PATCH", body: { status } });

/** @param {string} month @returns {Promise<Allowance[]>} */
export const getAllowances = (month) => apiFetch(`/billing/allowances${monthQuery(month)}`);

/** @param {string} childId @param {string} month @param {number} budget @returns {Promise<Allowance>} */
export const setBudget = (childId, month, budget) =>
  apiFetch(`/billing/allowances/${childId}`, { method: "PUT", body: { month, budget } });

/**
 * 용돈 사용 기록. 남은 금액보다 크면 서버가 over_budget 오류로 거절한다.
 * @param {string} childId
 * @param {{ amount: number, memo: string, date?: string }} body
 * @returns {Promise<Allowance>}
 */
export const addAllowanceUse = (childId, body) =>
  apiFetch(`/billing/allowances/${childId}/uses`, { method: "POST", body });
