import { apiFetch } from "@/shared/api/client";

/**
 * 일정 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /schedule/* 를 따른다.
 * 화면이 쓰는 항목(ScheduleItem)과 서버 일정(Event)의 변환(toItem·toBody)도 여기서 한다. 변환은 가족 id 변환기(members.js 의 buildFamily)를 받는다.
 * @typedef {{ id: string, title: string, starts_at: string, kind: 1 | 2, who_ids: string[], place: string, start_date: string | null, start_time: string | null, end_time: string | null, memo: string, note: string, checked: boolean, created_by: string, origin_id: string | null, topic_id: string | null }} ServerEvent
 * @typedef {{ id: string, name: string, color: string, created_at: string }} ServerTopic
 * @typedef {{ shared_by: string | null, shared_with: string[] }} Sharing
 * @typedef {ReturnType<import("./members").buildFamily>} Family
 * @typedef {{ intent: string, text: string, cards: { type: string, data: Record<string, any> }[], pending_action: object | null, draft: object | null }} AgentResponse
 */

const KIND_FROM_SERVER = { 1: "appointment", 2: "todo" };
const KIND_TO_SERVER = { appointment: 1, todo: 2 };
// 서버에는 종일 칸이 없어서 00:00~23:59 를 종일로 저장하고 읽는다.
const ALL_DAY_START = "00:00";
const ALL_DAY_END = "23:59";

const hhmm = (time) => (time ? time.slice(0, 5) : null);

/** 서버 일정에 날짜가 없는 옛 줄은 시각(UTC)에서 이 기기의 날짜를 읽는다. */
function dateOf(event) {
  if (event.start_date) return event.start_date;
  const d = new Date(event.starts_at);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * 서버 일정 → 화면 항목. 서버가 내 줄만 돌려주므로 모두 내 일정이다. 공유 대상은 서버 목록에 없어 비워 두고, 상세가 getSharing 으로 채운다.
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
    whoIds: event.who_ids.map(family.toApp).filter(Boolean),
    topicId: event.topic_id,
    sharedWith: [],
    createdBy: family.toApp(event.created_by) ?? event.created_by,
    checked: event.checked,
  };
}

/**
 * 화면 항목의 값 → 서버 요청 본문. 수정(PATCH)은 시간을 null 로 보내야 지워지므로 항상 모든 값을 보낸다.
 * 공유(share_with)는 등록할 때만 보낸다.
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
    who_ids: (item.whoIds ?? []).map(family.toUser).filter(Boolean),
    topic_id: item.topicId ?? null,
  };
  if (create) body.share_with = (item.sharedWith ?? []).map(family.toUser).filter(Boolean);
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
  if ("whoIds" in patch) body.who_ids = full.who_ids;
  if ("topicId" in patch) body.topic_id = full.topic_id;
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

/** 내 주제 목록(처음이면 서버가 기본 주제 "경조사"를 만들어 준다). @returns {Promise<ServerTopic[]>} */
export const listTopics = () => apiFetch("/schedule/topics");

/** 이 일정을 누가 공유했는지, 누구에게 공유했는지(상세 화면에서만 부른다). @returns {Promise<Sharing>} */
export const getSharing = (id) => apiFetch(`/schedule/events/${id}/sharing`);

/**
 * 일정 에이전트에게 말을 보낸다. draft 는 직전 응답이 되물으며 돌려준 초안(없으면 새 요청).
 * @param {string} text
 * @param {object | null} draft
 * @returns {Promise<AgentResponse>}
 */
export const askAgent = (text, draft = null) =>
  apiFetch("/schedule/agent", { method: "POST", body: { text, channel: "personal", draft } });

/**
 * 확인 카드의 버튼(AI 를 부르지 않는다). 등록 확인에서 share 가 false 면 공유 대상을 빼고 내 일정만 만든다.
 * @param {object} action 응답의 pending_action
 * @param {boolean} [share]
 * @returns {Promise<AgentResponse>}
 */
export const confirmAgent = (action, share = true) =>
  apiFetch("/schedule/agent/confirm", { method: "POST", body: { action, share } });
