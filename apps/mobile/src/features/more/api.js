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
 * 가비 기록(문서) 목록. 민감 문서 제외는 호출한 쪽이 한다.
 * @returns {Promise<object[]>} ItemOut[]
 */
export const listSharedDocuments = () => apiFetch("/ai-assistant/knowledge/items?limit=200");
