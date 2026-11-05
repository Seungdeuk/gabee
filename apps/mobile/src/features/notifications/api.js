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

/**
 * 이 기기의 푸시 토큰을 서버에 등록한다(같은 토큰이면 갱신).
 * @param {{ token: string, platform: "android" | "ios", deviceLabel?: string | null }} input
 * @returns {Promise<void>}
 */
export const registerPushToken = ({ token, platform, deviceLabel }) =>
  apiFetch("/notifications/push-token", {
    method: "PUT",
    body: { token, platform, device_label: deviceLabel ?? null },
  });

/**
 * 이 기기의 푸시 토큰을 서버에서 해제한다(로그아웃 때).
 * @param {string} token
 * @returns {Promise<void>}
 */
export const unregisterPushToken = (token) =>
  apiFetch("/notifications/push-token", { method: "DELETE", body: { token } });

/**
 * 내 푸시 설정.
 * @returns {Promise<{ enabled: boolean, preview_mode: "full" | "sender" | "hidden", muted_kinds: string[], quiet_start: string | null, quiet_end: string | null }>}
 */
export const getPushSettings = () => apiFetch("/notifications/push-settings");

/**
 * 내 푸시 설정을 저장한다.
 * @param {{ enabled: boolean, preview_mode: "full" | "sender" | "hidden", muted_kinds: string[], quiet_start: string | null, quiet_end: string | null }} settings
 * @returns {Promise<object>} 저장된 설정
 */
export const savePushSettings = (settings) => apiFetch("/notifications/push-settings", { method: "PUT", body: settings });
