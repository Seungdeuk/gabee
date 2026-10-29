import { apiFetch } from "@/shared/api/client";

/**
 * 쿼리 문자열을 만든다. 비어 있는 값은 뺀다.
 * @param {Record<string, string | number | null | undefined>} params
 * @returns {string} "?a=1&b=2" 또는 ""
 */
function queryString(params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

/**
 * 내 알림 목록(최신순). cursor 는 이전 응답의 next_cursor.
 * @param {{ kind?: string | null, limit?: number, cursor?: string | null }} [options]
 * @returns {Promise<{ items: Array<object>, next_cursor: string | null }>}
 */
export const listNotifications = ({ kind, limit, cursor } = {}) =>
  apiFetch(`/notifications${queryString({ kind, limit, cursor })}`);

/**
 * 안 읽은 알림 개수.
 * @returns {Promise<{ total: number, by_kind: Record<string, number> }>}
 */
export const getUnreadCount = () => apiFetch("/notifications/unread-count");

/**
 * 알림 하나를 읽음 처리한다.
 * @param {string} id
 * @returns {Promise<object>} 읽음 처리된 알림
 */
export const markRead = (id) => apiFetch(`/notifications/${id}/read`, { method: "POST" });

/**
 * 안 읽은 알림을 모두 읽음 처리한다. kind 를 주면 그 분류만.
 * @param {string} [kind]
 * @returns {Promise<{ updated: number }>}
 */
export const markAllRead = (kind) => apiFetch("/notifications/read-all", { method: "POST", body: kind ? { kind } : {} });
