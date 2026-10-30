import { apiFetch } from "@/shared/api/client";

/**
 * 일정 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /schedule/* 를 따른다.
 * 화면이 쓰는 항목(ScheduleItem)과 서버 일정(Event)의 변환(toItem·toBody)도 여기서 한다. 변환은 가족 id 변환기(members.js 의 buildFamily)를 받는다.
 * @typedef {{ id: string, title: string, starts_at: string, kind: 1 | 2, place: string, start_date: string | null, start_time: string | null, end_time: string | null, memo: string, note: string, checked: boolean, created_by: string, origin_id: string | null, topic_id: string | null }} ServerEvent
 * @typedef {{ id: string, name: string, color: string, created_at: string }} ServerTopic
 * @typedef {{ shared_by: string | null, shared_with: string[] }} Sharing
 * @typedef {ReturnType<import("./members").buildFamily>} Family
 * @typedef {{ id: string, title: string, kind: 1 | 2, start_date: string, place: string, later: boolean }} ServerSuggestion
 * @typedef {{ suggestions: ServerSuggestion[], exhausted: boolean, state: "ok" | "exhausted" | "no_data" | "filtered" | "preparing", can_refresh: boolean }} SuggestionList
 * @typedef {{ user_id: string, status: "waiting" | "accepted" | "declined" }} ServerRecipient
 * @typedef {{ id: string, from_id: string, title: string, start_date: string, start_time: string | null, end_time: string | null, place: string, memo: string, created_at: string, canceled: boolean, recipients: ServerRecipient[], my_event_id: string | null, edited_at?: string | null }} ServerRequest
 */

const KIND_FROM_SERVER = { 1: "appointment", 2: "todo" };
const KIND_TO_SERVER = { appointment: 1, todo: 2 };
// 서버에는 종일 칸이 없어서 00:00~23:59 를 종일로 저장하고 읽는다.
export const ALL_DAY_START = "00:00";
export const ALL_DAY_END = "23:59";

const hhmm = (time) => (time ? time.slice(0, 5) : null);

/** 서버 일정에 날짜가 없는 옛 줄은 시각(UTC)에서 이 기기의 날짜를 읽는다. */
function dateOf(event) {
  if (event.start_date) return event.start_date;
  const d = new Date(event.starts_at);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * 서버 일정 → 화면 항목. 서버가 내 줄만 돌려주므로 모두 내 일정이다. 공동 여부(shared)와 얽힌 사람(shared_ids)은 서버가 계산해 준다.
 * 공유 대상(sharedWith)은 서버 목록에 없어 비워 두고, 상세·수정 화면이 getSharing 으로 채운다.
 * @param {ServerEvent} event
 * @param {Family} family
 * @returns {import("./model").ScheduleItem}
 */
export function toItem(event, family) {
  const start = hhmm(event.start_time);
  const end = hhmm(event.end_time);
  const allDay = start === ALL_DAY_START && end === ALL_DAY_END;
  return {
    id: event.id,
    kind: KIND_FROM_SERVER[event.kind] ?? "appointment",
    title: event.title,
    date: dateOf(event),
    startTime: allDay ? null : start,
    endTime: allDay ? null : end,
    allDay,
    place: event.place ?? "",
    memo: event.memo || event.note || "",
    topicId: event.topic_id,
    sharedWith: [],
    shared: event.shared,
    sharedIds: (event.shared_ids ?? []).map(family.toApp).filter(Boolean),
    createdBy: family.toApp(event.created_by) ?? event.created_by,
    checked: event.checked,
  };
}

/**
 * 화면 항목의 값 → 서버 요청 본문. 수정(PATCH)은 시간을 null 로 보내야 지워지므로 항상 모든 값을 보낸다.
 * 추천 확정(suggestion_id: 이 일정이 내 대기 제안에서 왔을 때)은 등록할 때만 보낸다. 공유(share_with)는 등록 때 보내고, 수정에서는 toPatchBody 가 바꿨을 때만 보낸다.
 * @param {Partial<import("./model").ScheduleItem>} item
 * @param {Family} family
 * @param {{ create?: boolean }} [options]
 */
export function toBody(item, family, { create = false } = {}) {
  const body = {
    title: item.title,
    kind: KIND_TO_SERVER[item.kind],
    start_date: item.date,
    start_time: item.allDay ? ALL_DAY_START : (item.startTime ?? null),
    end_time: item.allDay ? ALL_DAY_END : item.startTime ? (item.endTime ?? null) : null,
    place: item.place ?? "",
    memo: item.memo ?? "",
    topic_id: item.topicId ?? null,
  };
  if (create) {
    body.share_with = (item.sharedWith ?? []).map(family.toUser).filter(Boolean);
    if (item.suggestionId) body.suggestion_id = item.suggestionId;
  }
  return body;
}

/**
 * 수정 요청 본문: 바꾼 값만 담는다(보내지 않은 값은 서버가 그대로 둔다).
 * @param {Partial<import("./model").ScheduleItem>} patch
 * @param {import("./model").ScheduleItem} current 바꾸기 전 항목(시간 처리에 필요)
 * @param {Family} family
 */
export function toPatchBody(patch, current, family) {
  const merged = { ...current, ...patch };
  const full = toBody(merged, family);
  const body = {};
  const touchesTime = ["date", "startTime", "endTime", "allDay"].some((key) => key in patch);
  if ("title" in patch) body.title = full.title;
  if ("kind" in patch) body.kind = full.kind;
  if ("place" in patch) body.place = full.place;
  if ("memo" in patch) body.memo = full.memo;
  if ("topicId" in patch) body.topic_id = full.topic_id;
  // 공유 대상 전체를 다시 정한다(원본 주인만. 빠진 사람의 복사본은 서버가 지운다).
  if ("sharedWith" in patch) body.share_with = (patch.sharedWith ?? []).map(family.toUser).filter(Boolean);
  if (touchesTime) {
    body.start_date = full.start_date;
    body.start_time = full.start_time;
    body.end_time = full.end_time;
  }
  return body;
}

/** 내 일정 전체(지난 것 포함). @returns {Promise<ServerEvent[]>} */
export const listEvents = () => apiFetch("/schedule/events?include_past=true");

/** @param {object} body toBody(..., { create: true }) @returns {Promise<ServerEvent>} */
export const createEvent = (body) => apiFetch("/schedule/events", { method: "POST", body });

/** @returns {Promise<ServerEvent>} */
export const updateEvent = (id, body) => apiFetch(`/schedule/events/${id}`, { method: "PATCH", body });

export const deleteEvent = (id) => apiFetch(`/schedule/events/${id}`, { method: "DELETE" });

/** @returns {Promise<ServerEvent>} */
export const setEventChecked = (id, checked) =>
  apiFetch(`/schedule/events/${id}/checked`, {
    method: "PUT",
    body: { checked },
  });

/**
 * 오늘의 대기 제안(없으면 서버가 만들어 주니 몇 초 걸릴 수 있다). 하루 몫을 다 쓰면 suggestions 가 비고 exhausted 가 true.
 * 최근 AI 채팅에서 내가 한 말(chat, 최대 30줄)을 함께 보낸다. 서버는 저장하지 않는다.
 * @param {string[]} [chat] suggest_chat.js 의 recentChatLines 결과
 * @returns {Promise<SuggestionList>}
 */
export const listSuggestions = (chat = []) => apiFetch("/schedule/suggestions", { method: "POST", body: { chat } });

/** 추천의 "나중에" 표시를 서버에 반영한다(true 면 나중에, false 면 다시 대기). */
export const setSuggestionLater = (id, later) =>
  apiFetch(`/schedule/suggestions/${id}/later`, { method: "PUT", body: { later } });

/** 내 주제 목록(처음이면 서버가 기본 주제 "경조사"를 만들어 준다). @returns {Promise<ServerTopic[]>} */
export const listTopics = () => apiFetch("/schedule/topics");

/** 주제를 만든다. 같은 이름이면 409 topic_exists, 이름이 잘못이면 400 invalid_topic(ApiError.code). @returns {Promise<ServerTopic>} */
export const createTopic = (name, color) => apiFetch("/schedule/topics", { method: "POST", body: { name, color } });

/** 주제를 지운다(204). 그 주제를 붙였던 일정은 서버가 topic_id 를 비운다. */
export const deleteTopic = (id) => apiFetch(`/schedule/topics/${id}`, { method: "DELETE" });

/** 이 일정을 누가 공유했는지, 누구에게 공유했는지(상세 화면에서만 부른다). @returns {Promise<Sharing>} */
export const getSharing = (id) => apiFetch(`/schedule/events/${id}/sharing`);

/** 같이(부탁) 목록: 내가 보낸 것과 받은 것, 최신순. @returns {Promise<ServerRequest[]>} */
export const listRequests = () => apiFetch("/schedule/requests");

/** 같이를 보낸다. @param {object} body together_convert.js 의 toRequestBody @returns {Promise<ServerRequest>} */
export const createRequest = (body) => apiFetch("/schedule/requests", { method: "POST", body });

/**
 * 받은 같이에 답한다. 수락이면 서버가 내 일정을 만든다(kind 필수: 1 약속·2 할 일).
 * @param {string} id
 * @param {"accepted" | "declined"} answer
 * @param {1 | 2 | null} [kind]
 * @returns {Promise<ServerRequest>}
 */
export const answerRequest = (id, answer, kind = null) =>
  apiFetch(`/schedule/requests/${id}/answer`, { method: "POST", body: { answer, kind } });

/** 보낸 사람이 부탁을 취소한다(수락한 사람이 있어도 되고, 그 사람의 일정은 서버가 지운다). @returns {Promise<ServerRequest>} */
export const cancelRequest = (id) => apiFetch(`/schedule/requests/${id}/cancel`, { method: "POST" });

/**
 * 보낸 사람이 받는 사람을 바꾼다(바뀐 뒤 전체 목록, 최소 1명, 나 제외). 빠진 사람의 부탁·그가 만든 일정은 서버가 지운다.
 * 400 invalid_recipients·request_canceled, 403 not_owner(ApiError.code).
 * @param {string} id
 * @param {string[]} toIds 서버 사용자 id
 * @returns {Promise<ServerRequest>}
 */
export const changeRecipients = (id, toIds) => apiFetch(`/schedule/requests/${id}/recipients`, { method: "PUT", body: { to_ids: toIds } });
