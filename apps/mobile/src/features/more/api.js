import { apiFetch } from "@/shared/api/client";

/**
 * 마이 탭(AI 리포트)이 쓰는 서버 호출. 다른 기능의 공개 API 계약(docs/contracts/openapi.json)만 쓰고,
 * 그 기능의 내부 파일은 가져오지 않는다. 서버 주소가 없으면 apiFetch 가 ApiError(0, "api_not_configured") 를 던진다.
 */

/**
 * 내 일정 전체(지난 일정 포함). 가족 공유 여부(shared)와 종류(kind)는 호출한 쪽이 가려 쓴다.
 * @returns {Promise<object[]>} EventOut[]
 */
export const listSharedEvents = () => apiFetch("/schedule/events?include_past=true");

/**
 * 오늘 AI 사용량과 하루 한도(가족 AI 설정 응답). 공개 계약의 `limits`·`usage` 만 읽는다.
 * @returns {Promise<{ limits?: { user_per_day?: number, group_per_day?: number }, usage?: { user_today?: number, group_today?: number } }>}
 */
export const getAiUsage = () => apiFetch("/family-chat/ai/settings");

/**
 * 가비 기록(문서) 목록. 민감 문서 제외는 호출한 쪽이 한다.
 * from·to 를 주면 서버가 올린 날(created_at, KST 날짜) 양끝 포함 범위로 거른다.
 * 서버가 구버전이면 범위를 무시하고 전체 최대 200건을 주므로 호출한 쪽이 다시 거른다.
 * @param {{ from?: string, to?: string }} [range] "YYYY-MM-DD". 둘 다 없으면 범위 없이 최대 200건
 * @returns {Promise<object[]>} ItemOut[]
 */
export const listSharedDocuments = ({ from, to } = {}) => {
  const query = new URLSearchParams({ limit: "200" });
  if (from && to) {
    query.set("created_from", from);
    query.set("created_to", to);
  }
  return apiFetch(`/ai-assistant/knowledge/items?${query.toString()}`);
};
