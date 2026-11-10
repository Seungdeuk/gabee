import { apiFetch } from "@/shared/api/client";

/**
 * 서비스 공지사항 목록(최근순 최대 100건). 계약은 서버 `GET /notices` (docs/requirements/notices.md)를 따른다.
 * 쓰기는 서비스 관리자 페이지에서만 한다.
 * @returns {Promise<{ rows: { id: string, category: "update" | "info" | "maintenance", title: string, body: string, created_at: string, updated_at: string }[] }>}
 */
export const listNotices = () => apiFetch("/notices");
