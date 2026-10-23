import { apiFetch } from "@/shared/api/client";

/**
 * 가족 채팅 AI 호출. 대화 글자는 앱이 보내지 않는다 — 범위(개수·시작 id)만 보내고 서버가 직접 읽는다.
 * 응답 형태는 서버 ai_schemas.py 가 기준이다.
 */

/**
 * AI 사용 설정(동의 여부·내 권한·한도·오늘 사용량).
 * @returns {Promise<{ enabled: boolean, can_manage: boolean, auto_analysis: boolean, limits: object, usage: { user_today: number, group_today: number } }>}
 */
export const getAiSettings = () => apiFetch("/family-chat/ai/settings");

/**
 * AI 사용을 켜거나 끈다(소유자·관리자만, 아니면 403 not_manager).
 * @param {boolean} enabled
 * @returns {Promise<object>} 바뀐 설정
 */
export const setAiEnabled = (enabled) => apiFetch("/family-chat/ai/settings", { method: "PUT", body: { enabled } });

const rangeBody = ({ limit = 100, afterId = 0 } = {}) => ({ limit, after_id: afterId });

/**
 * 대화 분석(요약·중요 메시지·일정 후보·할 일 후보를 한 번에). 누를 때만 호출한다.
 * @param {{ limit?: number, afterId?: number }} [range] 최근 limit 개(기본 100), afterId 를 주면 그 뒤의 대화
 * @returns {Promise<{ summary: string, important_messages: object[], schedule_candidates: object[], todo_candidates: object[], meta: object }>}
 */
export const analyzeChat = (range) => apiFetch("/family-chat/ai/analysis", { method: "POST", body: rangeBody(range) });

/**
 * 답장 추천(분석과 별개 요청).
 * @param {{ limit?: number, afterId?: number }} [range]
 * @returns {Promise<{ replies: string[], meta: object }>}
 */
export const suggestReplies = (range) => apiFetch("/family-chat/ai/replies", { method: "POST", body: rangeBody(range) });

/**
 * 대화 주제 추천(분석과 별개 요청).
 * @param {{ limit?: number, afterId?: number }} [range]
 * @returns {Promise<{ topics: string[], meta: object }>}
 */
export const suggestTopics = (range) => apiFetch("/family-chat/ai/topics", { method: "POST", body: rangeBody(range) });

/**
 * 일정 후보를 EventCreate 본문으로 바꾼다. 날짜·시간이 없거나 올바르지 않으면 null(지어내지 않는다).
 * 날짜·시간은 기기의 현재 시간대로 해석해 UTC 시각으로 보낸다.
 * @param {{ title: string, date?: string | null, time?: string | null, place?: string | null }} candidate
 * @returns {{ title: string, starts_at: string, note: string, status: string, source: string } | null}
 */
export function scheduleEventBody(candidate) {
  const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(candidate?.date ?? "");
  const time = /^(\d{2}):(\d{2})$/.exec(candidate?.time ?? "");
  const title = (candidate?.title ?? "").trim().slice(0, 120);
  if (!date || !time || !title) return null;
  const [y, mo, d, h, mi] = [date[1], date[2], date[3], time[1], time[2]].map(Number);
  const at = new Date(y, mo - 1, d, h, mi);
  if (at.getMonth() !== mo - 1 || at.getDate() !== d || at.getHours() !== h) return null; // 2월 31일·25시 같은 값
  return {
    title,
    starts_at: at.toISOString(),
    note: candidate.place ? `장소: ${candidate.place}` : "",
    status: "confirmed",
    source: "chat",
  };
}

/**
 * 사용자가 확인한 일정 후보를 서버 일정으로 등록한다(POST /schedule/events, EventCreate).
 * 일정 기능의 api 파일을 가져오지 않고 공통 래퍼로 계약대로 직접 호출한다.
 * @param {{ title: string, date: string | null, time: string | null, place?: string | null }} candidate 날짜·시간이 모두 있어야 한다
 * @returns {Promise<{ id: string, title: string, starts_at: string }>}
 */
export const registerScheduleCandidate = async (candidate) => {
  const body = scheduleEventBody(candidate);
  if (!body) throw new Error("날짜와 시간이 모두 있는 후보만 등록할 수 있어요");
  return apiFetch("/schedule/events", { method: "POST", body });
};

/**
 * 채팅 메시지 조회. 결과는 항상 오래된 순이다. 대화 글자는 쿼리에 넣지 않는다(숫자 범위만).
 * - latest: 가장 최근 limit 개 / beforeId: 그 id 보다 오래된 것 중 가장 최근 limit 개 / afterId: 그 id 뒤의 새 메시지
 * @param {{ latest?: boolean, beforeId?: number, afterId?: number, limit?: number }} [options] limit 기본 100, 최대 200
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string }[]>}
 */
export function listMessages({ latest = false, beforeId, afterId, limit = 100 } = {}) {
  const params = [];
  if (latest) params.push("latest=true");
  if (beforeId != null) params.push(`before_id=${Number(beforeId)}`);
  if (afterId != null) params.push(`after_id=${Number(afterId)}`);
  params.push(`limit=${Number(limit)}`);
  return apiFetch(`/family-chat/messages?${params.join("&")}`);
}

/**
 * 메시지를 보낸다(일반 전송은 AI 를 부르지 않는다).
 * @param {string} text 1~2000자
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string }>}
 */
export const sendMessage = (text) => apiFetch("/family-chat/messages", { method: "POST", body: { text } });

/**
 * 내 가족 그룹 정보(이름·구성원·내 id). 그룹이 없으면 404.
 * @returns {Promise<{ id: string, name: string, my_id: string | null, members: { id: string, name: string, display_name?: string | null }[] }>}
 */
export const getRoomInfo = () => apiFetch("/family-group/groups/me");
