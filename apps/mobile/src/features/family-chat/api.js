import { apiFetch } from "@/shared/api/client";

import { chatPhotoFileName, chatPhotoMimeType } from "./photo";

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
 * 대화방 id 를 쿼리 조각으로. 없으면(가족 전체방) 빈 문자열이라 이전 앱과 같은 요청이 된다.
 * @param {string | null | undefined} roomId
 * @returns {string}
 */
const roomParam = (roomId) => (roomId ? `room_id=${encodeURIComponent(roomId)}` : "");

/**
 * 대화방 목록: 가족 전체방(맨 위)과 내가 참여한 1:1 방. AI 를 부르지 않는다.
 * @returns {Promise<{ id: string, kind: "family" | "direct", peer_user_id: string | null, last_message: { id: number, user_id: string, user_name: string, text: string, created_at: string } | null, unread: number }[]>}
 */
export const listRooms = () => apiFetch("/family-chat/rooms");

/**
 * 같은 가족 구성원과의 1:1 방을 열거나(없으면 만든다) 돌려준다.
 * @param {string} userId 상대 구성원 id
 * @returns {Promise<{ id: string, kind: "direct", peer_user_id: string, last_message: object | null, unread: number }>}
 */
export const openDirectRoom = (userId) => apiFetch("/family-chat/rooms/direct", { method: "POST", body: { user_id: userId } });

/**
 * 채팅 메시지 조회. 결과는 항상 오래된 순이다. 대화 글자는 쿼리에 넣지 않는다(숫자 범위만).
 * - latest: 가장 최근 limit 개 / beforeId: 그 id 보다 오래된 것 중 가장 최근 limit 개 / afterId: 그 id 뒤의 새 메시지
 * @param {{ latest?: boolean, beforeId?: number, afterId?: number, limit?: number, roomId?: string | null }} [options] limit 기본 100, 최대 200, roomId 가 없으면 가족 전체방
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string, attachment?: { id: string, kind: string, url: string, thumb_url: string, width: number, height: number } | null }[]>}
 */
export function listMessages({ latest = false, beforeId, afterId, limit = 100, roomId } = {}) {
  const params = [];
  if (latest) params.push("latest=true");
  if (beforeId != null) params.push(`before_id=${Number(beforeId)}`);
  if (afterId != null) params.push(`after_id=${Number(afterId)}`);
  params.push(`limit=${Number(limit)}`);
  if (roomId) params.push(roomParam(roomId));
  return apiFetch(`/family-chat/messages?${params.join("&")}`);
}

/**
 * 메시지를 보낸다(일반 전송은 AI 를 부르지 않는다).
 * @param {string} text 1~2000자
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string, attachment?: { id: string, kind: string, url: string, thumb_url: string, width: number, height: number } | null }>}
 */
export const sendMessage = (text, roomId) => apiFetch("/family-chat/messages", { method: "POST", body: roomId ? { text, room_id: roomId } : { text } });

/**
 * 사진 메시지를 보낸다(POST /family-chat/photos, multipart 'file' + 선택 form 필드 room_id). 8MB 이하 JPEG/PNG/WebP, 서버가 다시 만든다. AI 를 부르지 않는다.
 * 웹은 asset.file(없으면 asset.uri 의 blob)을 그대로, 네이티브는 {uri, name, type} 으로 보낸다. Content-Type 은 fetch 가 boundary 와 함께 붙인다.
 * @param {{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string }} asset expo-image-picker 가 돌려준 asset
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방(form 에 넣지 않는다)
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string, attachment: { id: string, kind: "image", url: string, thumb_url: string, width: number, height: number } | null }>}
 */
export async function sendPhoto(asset, roomId) {
  const name = chatPhotoFileName(asset);
  const type = chatPhotoMimeType(asset);
  const form = new FormData();
  if (asset.file) {
    form.append("file", asset.file, name);
  } else if (/^(blob|data):/.test(asset.uri)) {
    const blob = await (await fetch(asset.uri)).blob();
    form.append("file", blob, name);
  } else {
    form.append("file", { uri: asset.uri, name, type });
  }
  if (roomId) form.append("room_id", roomId);
  return apiFetch("/family-chat/photos", { method: "POST", body: form });
}

/**
 * 내 가족 그룹 정보(이름·구성원·내 id). 그룹이 없으면 404.
 * @returns {Promise<{ id: string, name: string, my_id: string | null, members: { id: string, name: string, display_name?: string | null, photo_url?: string | null }[] }>}
 */
export const getRoomInfo = () => apiFetch("/family-group/groups/me");

/**
 * 내 읽음 위치를 올린다(서버는 단조 증가만 허용). 대화 글자는 보내지 않고 메시지 번호만 보낸다. AI 를 부르지 않는다.
 * @param {number} messageId 내가 읽은 가장 큰 서버 메시지 id(1 이상)
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방
 * @returns {Promise<{ last_read_message_id: number }>}
 */
export const markRead = (messageId, roomId) =>
  apiFetch("/family-chat/read", { method: "POST", body: roomId ? { message_id: Number(messageId), room_id: roomId } : { message_id: Number(messageId) } });

/**
 * 방 참여자 전원의 읽음 위치. AI 를 부르지 않는다.
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방
 * @returns {Promise<{ user_id: string, last_read_message_id: number }[]>}
 */
export const getReadStates = (roomId) => apiFetch(roomId ? `/family-chat/read-states?${roomParam(roomId)}` : "/family-chat/read-states");

/**
 * 내가 아직 읽지 않은 다른 사람의 메시지 수(서버가 최대 1000 까지 센다). AI 를 부르지 않는다.
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방
 * @returns {Promise<{ unread: number, last_read_message_id: number }>}
 */
export const getUnread = (roomId) => apiFetch(roomId ? `/family-chat/unread?${roomParam(roomId)}` : "/family-chat/unread");
