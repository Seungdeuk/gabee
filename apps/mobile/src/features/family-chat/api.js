import { apiFetch, apiUrl, authHeaders, ensureFreshAccess, isApiConfigured } from "@/shared/api/client";
import { mapChatCards } from "@/features/ai-assistant/scheduleCard";
import { getGroupWithNicknames } from "@/shared/members/nicknames";
import { photoPath } from "@/shared/photoCache";

import { chatFileMimeType } from "./fileUtils";
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

const rangeBody = ({ limit = 100, afterId = 0, roomId } = {}) => ({ limit, after_id: afterId, ...(roomId ? { room_id: roomId } : {}) });

/**
 * 가족 채팅방에서 @가비 로 부른 질문을 메인 AI 비서에게 보낸다(개인 대화와 같은 입구, 같은 한도).
 * 서버가 답을 가비 이름으로 가족 전체방에 저장한다(앱이 다시 올리지 않는다). 확인 버튼이 필요한 요청은 질문한 사람 응답에만 카드로 온다.
 * history 는 내가 @가비 로 나눈 앞 대화뿐이다(방의 다른 사람 글은 보내지 않는다).
 * @param {string} question @가비 를 뺀 질문
 * @param {{ role: "user" | "assistant", text: string }[]} [history]
 * @param {string} [roomId] 1:1 방에서 부른 것이면 그 방 id(답을 그 1:1 방에 저장한다). 없으면 가족 전체방
 * @returns {Promise<{ reply: string, postedMessageId: number | null, confirmCards: object[] }>} postedMessageId 가 null 이면 서버가 방에 저장하지 않은 답(구 서버)
 */
export async function askAssistantInRoom(question, history = [], roomId) {
  const turns = history.slice(-10).map(({ role, text }) => ({ role, text }));
  const res = await apiFetch("/ai-assistant/chat", { method: "POST", body: { message: question, audience: "room", history: turns, ...(roomId ? { room_id: roomId } : {}) } });
  return {
    reply: res.reply ?? "",
    postedMessageId: res.posted_message_id ?? null,
    confirmCards: mapChatCards(res), // 확인 버튼이 필요한 일정 요청·정산/돌봄 제안은 질문한 사람 화면에만 카드로 보인다
  };
}

/**
 * 대화 분석(요약·중요 메시지·일정 후보·할 일 후보·답장 추천·대화 주제 추천을 한 번에). 누를 때만 호출한다.
 * replies·topics 는 구 서버 응답에 없을 수 있다(parseAnalysis 로 방어).
 * @param {{ limit?: number, afterId?: number, roomId?: string }} [range] 최근 limit 개(기본 100), afterId 를 주면 그 뒤의 대화, roomId 를 주면 그 1:1 방의 대화(없으면 가족 전체방)
 * @returns {Promise<{ summary: string, important_messages: object[], schedule_candidates: object[], todo_candidates: object[], replies?: string[], topics?: string[], meta: object }>}
 */
export const analyzeChat = (range) => apiFetch("/family-chat/ai/analysis", { method: "POST", body: rangeBody(range) });

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
 * 채팅 사진을 AI 비서의 가족 기록으로 올린다(POST /ai-assistant/files, multipart 'file'). AI 비서 기능의 api 파일을 가져오지 않고
 * 공통 래퍼로 계약대로 직접 호출한다. 서버는 받자마자 received 로 응답하고 읽기·가리기·분류·저장은 뒤에서 한다.
 * @param {FormData} form 'file' 한 개를 담은 폼(웹은 Blob, 네이티브는 {uri, name, type})
 * @returns {Promise<{ id: string, filename: string, status: string }>}
 */
export const uploadToAssistantRecord = (form) => apiFetch("/ai-assistant/files", { method: "POST", body: form });

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
 * @returns {Promise<{ id: string, kind: "family" | "direct", peer_user_id: string | null, last_message: { id: number, user_id: string, user_name: string, text: string, created_at: string } | null, unread: number, muted?: boolean }[]>} muted 는 내 알림 끔 여부(없으면 false)
 */
export const listRooms = () => apiFetch("/family-chat/rooms");

/**
 * 같은 가족 구성원과의 1:1 방을 열거나(없으면 만든다) 돌려준다.
 * @param {string} userId 상대 구성원 id
 * @returns {Promise<{ id: string, kind: "direct", peer_user_id: string, last_message: object | null, unread: number, muted?: boolean }>}
 */
export const openDirectRoom = (userId) => apiFetch("/family-chat/rooms/direct", { method: "POST", body: { user_id: userId } });

/**
 * 이 방의 알림을 끄거나 켠다(내 설정만 바뀐다. 푸시는 아직 없어 저장만 하고, 읽지 않음 숫자는 그대로다).
 * @param {string} roomId 방 목록의 방 id(가족 전체방은 kind "family" 행의 id)
 * @param {boolean} muted true 면 끔
 * @returns {Promise<{ room_id: string, muted: boolean }>}
 */
export const setRoomMuted = (roomId, muted) => apiFetch(`/family-chat/rooms/${encodeURIComponent(roomId)}/mute`, { method: "PUT", body: { muted: Boolean(muted) } });

/**
 * 채팅 메시지 조회. 결과는 항상 오래된 순이다. 대화 글자는 쿼리에 넣지 않는다(숫자 범위만).
 * - latest: 가장 최근 limit 개 / beforeId: 그 id 보다 오래된 것 중 가장 최근 limit 개 / afterId: 그 id 뒤의 새 메시지
 * - aroundId: 그 메시지를 가운데로 앞뒤 메시지(검색 결과로 이동할 때). 서버 계약은 별도 PR 의 `around_id` 이고, 다른 범위 옵션과 함께 쓰지 않아 aroundId 가 있으면 나머지 범위는 무시한다.
 * @param {{ latest?: boolean, beforeId?: number, afterId?: number, aroundId?: number, limit?: number, roomId?: string | null }} [options] limit 기본 100, 최대 200, roomId 가 없으면 가족 전체방
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string, attachment?: { id: string, kind: string, url: string, thumb_url: string, width: number, height: number } | null }[]>}
 */
export function listMessages({ latest = false, beforeId, afterId, aroundId, limit = 100, roomId } = {}) {
  const params = [];
  if (aroundId != null) {
    params.push(`around_id=${Number(aroundId)}`);
  } else {
    if (latest) params.push("latest=true");
    if (beforeId != null) params.push(`before_id=${Number(beforeId)}`);
    if (afterId != null) params.push(`after_id=${Number(afterId)}`);
  }
  params.push(`limit=${Number(limit)}`);
  if (roomId) params.push(roomParam(roomId));
  return apiFetch(`/family-chat/messages?${params.join("&")}`);
}

/**
 * 대화 글자 검색(키워드 일치만, 임베딩·AI 없음). 서버 계약은 별도 PR 의 `GET /family-chat/search` 다.
 * 공백으로 나눈 모든 낱말이 글자로 포함된 텍스트 메시지만(사진 메시지 제외) 최신순으로 온다. roomId 가 없으면 내가 접근할 수 있는 모든 방.
 * 검색어는 요청 주소에만 들어가고(인코딩) 앱은 어디에도 기록하지 않는다. 오류: 422(검색어 길이), 429(분당 횟수), 404(권한 없는 방), 401.
 * @param {{ q: string, roomId?: string | null, limit?: number, beforeId?: number | null }} options q 1~100자, limit 1~50(기본 20), beforeId 는 직전 응답의 next_before_id
 * @returns {Promise<{ items: { id: number, room_id: string, room_kind: "family" | "direct", peer_user_id: string | null, user_id: string, user_name: string, text: string, created_at: string }[], next_before_id: number | null }>}
 */
export function searchMessages({ q, roomId, limit = 20, beforeId } = {}) {
  const params = [`q=${encodeURIComponent(String(q ?? ""))}`];
  if (roomId) params.push(roomParam(roomId));
  params.push(`limit=${Number(limit)}`);
  if (beforeId != null) params.push(`before_id=${Number(beforeId)}`);
  return apiFetch(`/family-chat/search?${params.join("&")}`);
}

/**
 * 메시지를 보낸다(일반 전송은 AI 를 부르지 않는다).
 * @param {string} text 1~2000자
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방
 * @param {number | null} [replyToId] 답장할 메시지 id(같은 방의 지우지 않은 메시지, 아니면 400 invalid_message / reply_deleted)
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string, attachment?: { id: string, kind: string, url: string, thumb_url: string, width: number, height: number } | null }>}
 */
export const sendMessage = (text, roomId, replyToId) => {
  const body = roomId ? { text, room_id: roomId } : { text };
  if (replyToId != null) body.reply_to_id = Number(replyToId);
  return apiFetch("/family-chat/messages", { method: "POST", body });
};

/**
 * 내가 보낸 메시지를 지운다(본문·사진도 서버에서 비운다). 이미 지웠으면 같은 결과. 오류: 403(남의 메시지·가비의 답), 404(방·메시지 없음), 429.
 * @param {{ roomId?: string | null, messageId: number }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<object>} 지운 메시지(deleted: true, text 는 빈 글자)
 */
export const deleteMessage = ({ roomId, messageId }) => apiFetch(`/family-chat/messages/${Number(messageId)}${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "DELETE" });

/**
 * since 이후에 지워진 이 방의 메시지 id(지운 순서, 최대 200개)와 서버 시각. 새 메시지만 조회하는 앱이 이미 받아 둔 메시지가 지워졌음을 알려고 쓴다.
 * 응답의 server_time 을 다음 조회의 since 로 쓰면 기기 시계가 어긋나도 놓치지 않는다.
 * @param {{ roomId?: string | null, since: string }} options since 는 ISO 시각
 * @returns {Promise<{ message_ids: number[], server_time: string }>}
 */
export const listDeletedMessages = ({ roomId, since }) => apiFetch(`/family-chat/messages/deleted?since=${encodeURIComponent(since)}${roomId ? `&${roomParam(roomId)}` : ""}`);

/**
 * 메시지에 내 반응을 정한다(한 사람이 한 메시지에 하나, 다른 이모지면 바뀐다). 허용 이모지 6개(❤️ 👍 😂 😮 😢 🙏)만. 오류: 400 invalid_reaction / message_deleted, 404.
 * @param {{ roomId?: string | null, messageId: number, emoji: string }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<object>} 반응이 반영된 메시지(reactions: [{emoji, count, mine}])
 */
export const reactToMessage = ({ roomId, messageId, emoji }) => apiFetch(`/family-chat/messages/${Number(messageId)}/reaction${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "PUT", body: { emoji } });

/**
 * 내 반응을 지운다(없어도 같은 결과).
 * @param {{ roomId?: string | null, messageId: number }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<object>} 반응이 반영된 메시지
 */
export const removeReaction = ({ roomId, messageId }) => apiFetch(`/family-chat/messages/${Number(messageId)}/reaction${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "DELETE" });

/**
 * 사진 메시지를 보낸다(POST /family-chat/photos, multipart 'file' + 선택 form 필드 room_id). 8MB 이하 JPEG/PNG/WebP, 서버가 다시 만든다. AI 를 부르지 않는다.
 * 웹은 asset.file(없으면 asset.uri 의 blob)을 그대로, 네이티브는 {uri, name, type} 으로 보낸다. Content-Type 은 fetch 가 boundary 와 함께 붙인다.
 * @param {{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string }} asset expo-image-picker 가 돌려준 asset
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방(form 에 넣지 않는다)
 * @param {string | null} [batchId] 한 번에 여러 장 올릴 때 장마다 같은 묶음 번호(없으면 form 에 넣지 않는다)
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string, attachment: { id: string, kind: "image", url: string, thumb_url: string, width: number, height: number, batch_id: string | null } | null }>}
 */
export async function sendPhoto(asset, roomId, batchId) {
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
  if (batchId) form.append("batch_id", batchId);
  return apiFetch("/family-chat/photos", { method: "POST", body: form });
}

/**
 * 문서 파일 메시지를 보낸다(POST /family-chat/files, multipart 'file' + 선택 form 필드 room_id). 허용 형식·20MB 는 서버가 다시 검사한다. AI 를 부르지 않는다.
 * 웹은 asset.file(없으면 asset.uri 의 blob)을 그대로, 네이티브는 {uri, name, type} 으로 보낸다.
 * @param {{ uri: string, name?: string | null, mimeType?: string | null, file?: Blob }} asset expo-document-picker 의 asset
 * @param {string | null} [roomId] 대화방 id, 없으면 가족 전체방(form 에 넣지 않는다)
 * @returns {Promise<{ id: number, user_id: string, user_name: string, text: string, created_at: string, attachment: { id: string, kind: "file", url: string, thumb_url: string | null, width: number | null, height: number | null, filename: string | null, size_bytes: number | null, content_type: string | null } | null }>}
 */
export async function sendFile(asset, roomId) {
  const name = asset.name || "file";
  const type = chatFileMimeType({ name, mimeType: asset.mimeType });
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
  return apiFetch("/family-chat/files", { method: "POST", body: form });
}

// 서버가 만드는 파일 첨부 경로만 받는다(다른 주소로 인증 헤더가 나가지 않게)
const CHAT_FILE_PATH = /^\/family-chat\/files\/[\w-]+$/;

/**
 * 파일 받기 요청(주소+인증 헤더). 낯선 경로나 서버 주소가 없으면 던진다.
 * @param {string} path attachment.url
 * @returns {Promise<{ url: string, headers: Record<string, string> }>}
 */
export async function fileDownloadRequest(path) {
  if (typeof path !== "string" || !CHAT_FILE_PATH.test(path) || !isApiConfigured()) throw new Error("file_unavailable");
  await ensureFreshAccess().catch(() => {});
  return { url: apiUrl(path), headers: { ...authHeaders() } };
}

/**
 * 웹: 로그인 헤더로 파일을 받아 blob 으로 돌려준다.
 * @param {string} path attachment.url
 * @returns {Promise<Blob>}
 */
export async function downloadFile(path) {
  const { url, headers } = await fileDownloadRequest(path);
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error("file_unavailable");
  return res.blob();
}

/**
 * 내 가족 그룹 정보(이름·구성원·내 id). 그룹이 없으면 404. 구성원의 display_name 은 내가 붙인 별명이 있으면 별명으로 바뀌어 온다(raw 면 서버 값 그대로).
 * @param {{ raw?: boolean }} [options]
 * @returns {Promise<{ id: string, name: string, my_id: string | null, members: { id: string, name: string, display_name?: string | null, photo_url?: string | null }[] }>}
 */
export const getRoomInfo = ({ raw = false } = {}) => (raw ? apiFetch("/family-group/groups/me") : getGroupWithNicknames());

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

/**
 * 함께하기(일정 탭의 같이 요청)를 보낸다(POST /schedule/requests, RequestCreate). 일정 기능의 api 파일을 가져오지 않고 공통 래퍼로 계약대로 직접 호출한다.
 * @param {{ title: string, start_date: string, to_ids: string[] }} body 제목 1~120자, 날짜 YYYY-MM-DD, 받는 사람(나 제외) 1~20명
 * @returns {Promise<{ id: string, title: string, start_date: string }>}
 */
export const sendTogetherRequest = (body) => apiFetch("/schedule/requests", { method: "POST", body });

/**
 * 일정 탭의 내 일정·할 일(지난 것 포함, 서버가 내 줄만 돌려준다). 시간 없는 오늘 할 일은 자정이 지나면 "앞으로의 것"에서 빠지므로 지난 것까지 받고, 서랍 "가족 할 일" 화면이 오늘 이후의 할 일만 골라 쓴다.
 * @returns {Promise<{ id: string, title: string, kind: number, start_date: string | null, start_time: string | null, checked: boolean, origin_id: string | null }[]>}
 */
export const listScheduleEvents = () => apiFetch("/schedule/events?include_past=true");

/**
 * 같이(함께하기) 목록: 내가 보낸 것과 받은 것, 최신순.
 * @returns {Promise<{ id: string, from_id: string, title: string, start_date: string, start_time: string | null, canceled: boolean, recipients: { user_id: string, status: "waiting" | "accepted" | "declined" }[] }[]>}
 */
export const listTogetherRequests = () => apiFetch("/schedule/requests");

/**
 * 내가 다른 구성원에게 붙인 별명·메모(나만 보인다). family-group 기능의 파일을 가져오지 않고 계약대로 직접 호출한다.
 * @returns {Promise<{ target_user_id: string, nickname: string | null, memo: string | null }[]>}
 */
export const listNicknames = () => apiFetch("/family-group/groups/me/nicknames");

/**
 * 별명·메모를 정한다. 둘 다 비우면 서버가 지운다(빈 값은 null 로 보낸다).
 * @param {string} targetUserId 대상 구성원 id(나 자신은 400 cannot_nickname_self)
 * @param {{ nickname?: string, memo?: string }} value
 * @returns {Promise<{ target_user_id: string, nickname: string | null, memo: string | null }>}
 */
export const setNickname = (targetUserId, { nickname = "", memo = "" } = {}) =>
  apiFetch(`/family-group/groups/me/nicknames/${encodeURIComponent(targetUserId)}`, {
    method: "PUT",
    body: { nickname: nickname.trim() || null, memo: memo.trim() || null },
  });

/**
 * 채팅방의 사진 모음(최신 먼저, 커서 방식). 서버 계약은 별도 PR 이며 이 형태를 기준으로 한다. AI 를 부르지 않는다.
 * 오류: 404(들어갈 수 없는 방), 429(분당 60회), 401.
 * @param {{ roomId?: string | null, kind?: "image" | "file" | "video" | "all", limit?: number, beforeId?: number | null }} [options] roomId 가 없으면 가족 전체방, limit 1~100(기본 40), beforeId 는 이전 응답의 next_before_id
 * @returns {Promise<{ items: { attachment_id: string, message_id: number, kind: "image", user_id: string, user_name: string, created_at: string, url: string, thumb_url: string | null, width: number | null, height: number | null, size_bytes: number | null }[], next_before_id: number | null, counts: { image: number, file: number, video: number } }>}
 */
export function listMedia({ roomId, kind = "image", limit = 40, beforeId } = {}) {
  const params = [];
  if (roomId) params.push(roomParam(roomId));
  params.push(`kind=${["image", "file", "video", "all"].includes(kind) ? kind : "image"}`);
  params.push(`limit=${Math.min(100, Math.max(1, Math.floor(Number(limit)) || 40))}`);
  if (beforeId != null && Number(beforeId) >= 1) params.push(`before_id=${Math.floor(Number(beforeId))}`); // 서버는 1 이상만 받는다
  return apiFetch(`/family-chat/media?${params.join("&")}`);
}

/**
 * 채팅 사진 한 장을 가족 공유 문서함에 직접 넣는다("문서로 저장"). 가족 전체방 사진만 된다(1:1 방은 409 not_family_room, 없는 사진·못 들어가는 방은 404).
 * @param {string} attachmentId 사진 첨부 id(attachment.id)
 * @returns {Promise<{ status: "queued" | "already" }>} queued 는 저장을 시작했다(글을 읽는 데 시간이 걸린다), already 는 이미 문서함에 있다
 */
export const savePhotoToLibrary = (attachmentId) => apiFetch(`/family-chat/photos/${encodeURIComponent(attachmentId)}/library`, { method: "POST" });

/**
 * 사진 원본을 로그인 헤더로 받아 Blob 으로 돌려준다(웹 저장용). 서버가 준 사진 경로만 받고, 토큰은 주소에 넣지 않는다.
 * @param {string} path 서버가 준 attachment.url
 * @returns {Promise<Blob>}
 */
export async function downloadPhoto(path) {
  const safe = photoPath(path);
  if (!safe || !isApiConfigured()) throw new Error("photo_unavailable");
  await ensureFreshAccess().catch(() => {});
  const res = await fetch(apiUrl(safe), { headers: authHeaders() });
  if (!res.ok) throw new Error("photo_unavailable");
  return res.blob();
}

/**
 * 이 방에 고정된 메시지(최근 고정 2개, 최신순). 서버 계약은 별도 PR 의 `GET /family-chat/pins`. AI 를 부르지 않는다. 고정 내용은 기록하지 않는다.
 * @param {{ roomId?: string | null }} [options] roomId 가 없으면 가족 전체방
 * @returns {Promise<{ items: { message_id: number, text: string, text_truncated: boolean, user_id: string, user_name: string, created_at: string, pinned_by: string, pinned_by_name: string, pinned_at: string }[] }>}
 */
export const listPins = ({ roomId } = {}) => apiFetch(roomId ? `/family-chat/pins?${roomParam(roomId)}` : "/family-chat/pins");

/**
 * 메시지를 공지로 고정한다(방 안의 누구나, 텍스트 메시지만). 방당 최대 2개라 3번째면 가장 오래된 고정이 풀린다.
 * 오류: 400 invalid_message(그 방의 메시지 아님) / not_pinnable(사진이 있거나 빈 글), 404, 429(분당 30회).
 * @param {{ roomId?: string | null, messageId: number }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<{ item: object, replaced_message_id: number | null, already_pinned: boolean }>}
 */
export const pinMessage = ({ roomId, messageId }) =>
  apiFetch("/family-chat/pins", { method: "POST", body: roomId ? { room_id: roomId, message_id: Number(messageId) } : { message_id: Number(messageId) } });

/**
 * 고정을 푼다(방 안의 누구나). 메시지는 그대로 남는다. 고정이 아니면 404.
 * @param {{ roomId?: string | null, messageId: number }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<null>} 성공하면 본문 없음(204)
 */
export const unpinMessage = ({ roomId, messageId }) =>
  apiFetch(`/family-chat/pins/${Number(messageId)}${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "DELETE" });

/**
 * 게시판 공지를 나만 숨긴다(다른 구성원에게는 그대로 보인다, 이미 숨겼어도 같은 결과). 올라가 있지 않은 공지는 404.
 * @param {{ roomId?: string | null, messageId: number }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<object>} 서버 PinItem(hidden: true)
 */
export const hidePin = ({ roomId, messageId }) =>
  apiFetch(`/family-chat/pins/${Number(messageId)}/hide${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "PUT" });

/**
 * 숨겼던 공지를 다시 보이게 한다(숨기지 않았어도 같은 결과). 올라가 있지 않은 공지는 404.
 * @param {{ roomId?: string | null, messageId: number }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<object>} 서버 PinItem(hidden: false)
 */
export const showPin = ({ roomId, messageId }) =>
  apiFetch(`/family-chat/pins/${Number(messageId)}/hide${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "DELETE" });

/**
 * 게시판 목록: 공지로 올린 메시지의 기록(지난 공지 포함)을 올린 시각 최신순으로. 전체 본문이 온다. 서버 계약은 `GET /family-chat/board`. AI 를 부르지 않는다.
 * 오류: 400 invalid_cursor, 404(들어갈 수 없는 방), 429, 401.
 * @param {{ roomId?: string | null, limit?: number, before?: string | null }} [options] roomId 가 없으면 가족 전체방, limit 1~50(기본 20), before 는 이전 응답의 next_before
 * @returns {Promise<{ items: { id: string, message_id: number, text: string, user_id: string, user_name: string, message_created_at: string, posted_by: string, posted_by_name: string, posted_at: string, is_current: boolean, message_deleted: boolean }[], next_before: string | null }>}
 */
export function listBoard({ roomId, limit = 20, before } = {}) {
  const query = [roomParam(roomId), `limit=${Number(limit)}`, before ? `before=${encodeURIComponent(before)}` : ""].filter(Boolean).join("&");
  return apiFetch(`/family-chat/board?${query}`);
}

/**
 * 게시판 글을 삭제한다(방 안의 누구나). 지금 공지로 올라 있으면 채팅방 위 공지 바에서도 내려간다. 원본 메시지는 그대로다. 없는 글은 404.
 * @param {{ roomId?: string | null, postId: string }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<null>} 성공하면 본문 없음(204)
 */
export const deleteBoardPost = ({ roomId, postId }) =>
  apiFetch(`/family-chat/board/${encodeURIComponent(postId)}${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "DELETE" });

/**
 * 이 방에서 등록한 일정·할 일과 원본 메시지의 연결(최신순). 서버 계약은 별도 PR 의 `GET /family-chat/links`. AI 를 부르지 않는다. 제목·본문은 기록하지 않는다.
 * @param {{ roomId?: string | null, kind?: "event" | "todo" | null, limit?: number }} [options] roomId 가 없으면 가족 전체방, limit 1~100(기본 50)
 * @returns {Promise<{ items: { id: string, room_id: string, message_id: number, kind: "event" | "todo", target_id: string, title: string, date: string | null, time: string | null, created_by: string, created_by_name: string, created_at: string, message_text: string, message_user_name: string }[] }>}
 */
export function listLinks({ roomId, kind, limit = 50 } = {}) {
  const params = [];
  if (roomId) params.push(roomParam(roomId));
  if (kind === "event" || kind === "todo") params.push(`kind=${kind}`);
  params.push(`limit=${Math.min(100, Math.max(1, Math.floor(Number(limit)) || 50))}`);
  return apiFetch(`/family-chat/links?${params.join("&")}`);
}

/**
 * 등록한 일정·할 일을 원본 메시지에 연결한다(멱등: 이미 있으면 200 으로 그 연결). 새로 만들면 201.
 * 오류: 400 invalid_message(그 방의 텍스트 메시지 아님) / invalid_target / too_many_links, 404, 422, 429(분당 30회).
 * @param {{ roomId?: string | null, messageId: number, kind: "event" | "todo", targetId: string, title: string, date?: string | null, time?: string | null }} options roomId 가 없으면 가족 전체방, title 1~120자, date YYYY-MM-DD, time HH:MM
 * @returns {Promise<object>} 연결(LinkOut)
 */
export const createLink = ({ roomId, messageId, kind, targetId, title, date, time }) =>
  apiFetch("/family-chat/links", {
    method: "POST",
    body: {
      ...(roomId ? { room_id: roomId } : {}),
      message_id: Number(messageId),
      kind,
      target_id: String(targetId),
      title,
      ...(date ? { date } : {}),
      ...(time ? { time } : {}),
    },
  });

/**
 * 연결을 지운다(만든 사람만, 다른 구성원은 403 forbidden). 일정·할 일 자체와 메시지는 그대로 남는다. 없으면 404.
 * @param {{ roomId?: string | null, linkId: string }} options roomId 가 없으면 가족 전체방
 * @returns {Promise<null>} 성공하면 본문 없음(204)
 */
export const deleteLink = ({ roomId, linkId }) => apiFetch(`/family-chat/links/${encodeURIComponent(linkId)}${roomId ? `?${roomParam(roomId)}` : ""}`, { method: "DELETE" });

/**
 * 네이티브 저장용: 사진 원본을 내려받을 주소와 로그인 헤더를 만든다(토큰은 주소가 아니라 헤더에만 있다).
 * 서버가 준 사진 경로만 받고, 아니면 던진다. 실제 내려받기는 savePhoto.js 가 파일 시스템으로 한다.
 * @param {string} path 서버가 준 attachment.url
 * @returns {Promise<{ url: string, headers: Record<string, string> }>}
 */
export async function photoDownloadRequest(path) {
  const safe = photoPath(path);
  if (!safe || !isApiConfigured()) throw new Error("photo_unavailable");
  await ensureFreshAccess().catch(() => {});
  return { url: apiUrl(safe), headers: { ...authHeaders() } };
}
