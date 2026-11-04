import { apiFetch } from "@/shared/api/client";

/**
 * 문의·신고 서버 호출. 계약은 서버 `POST /support/tickets`·`GET /support/tickets/mine` (docs/requirements/support.md)를 따른다.
 * 서버 주소가 없으면 apiFetch 가 ApiError(0, "api_not_configured") 를 던진다.
 */

/**
 * 문의(inquiry)나 신고(report)를 보낸다. 사용자가 직접 쓴 제목과 내용만 보낸다(가족 채팅 내용은 붙이지 않는다).
 * @param {{ kind: "inquiry" | "report", title: string, body: string }} ticket
 * @returns {Promise<object>} TicketOut (id, kind, title, body, status, answer, answered_at, created_at)
 */
export const createTicket = ({ kind, title, body }) => apiFetch("/support/tickets", { method: "POST", body: { kind, title, body } });

/**
 * 내가 보낸 문의·신고와 답변(최근순 최대 100건).
 * @returns {Promise<{ rows: object[] }>} TicketList
 */
export const listMyTickets = () => apiFetch("/support/tickets/mine");
