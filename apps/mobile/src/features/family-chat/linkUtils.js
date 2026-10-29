// 메시지-일정/할 일 연결의 순수 함수(화면·네트워크와 분리해 시험한다). 메시지 글자·제목은 어디에도 기록하지 않는다.
import { parseTime } from "./chatUtils";
import { nextPinPollDelay, pinSettled, reloadGate } from "./pinUtils";

/** 한 번에 불러오는 연결 개수(서버 상한 100). 방 하나의 최근 연결을 이만큼만 쓴다. */
export const LINKS_LIMIT = 100;

export const TITLE_MAX = 120;

/** 종류 이름(목록 배지)과 말풍선 표시 문구. */
export const KIND_LABEL = { event: "일정", todo: "할 일" };
export const BADGE_LABEL = { event: "일정으로 등록됨", todo: "할 일로 등록됨" };

export const EMPTY_LINKS_TEXT = "아직 대화에서 등록한 일정·할 일이 없어요";
export const REMOVED_NOTICE = "연결만 지웠어요. 일정·할 일은 그대로예요";
export const BUSY_NOTICE = "처리 중이에요";

/** 연결 목록을 다시 조회하는 간격(밀리초). 고정 메시지와 같다. */
export const LINK_POLL_MS = 30000;

const TEMP_PREFIX = "tmp:";

/**
 * 서버에 저장되기 전(낙관적으로 먼저 그린) 연결인지.
 * @param {{ id?: unknown } | null | undefined} link
 * @returns {boolean}
 */
export const isTempLink = (link) => String(link?.id ?? "").startsWith(TEMP_PREFIX);

const isDay = (text) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text ?? ""));
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
};

const isClock = (text) => {
  const m = /^(\d{2}):(\d{2})$/.exec(String(text ?? ""));
  return Boolean(m) && Number(m[1]) < 24 && Number(m[2]) < 60;
};

/**
 * 제목 정리: 공백을 한 칸으로 줄이고 120 글자(코드포인트)까지만 남긴다. 이모지 같은 두 칸짜리 글자가 중간에서 잘려 깨지지 않게 한다.
 * @param {unknown} title
 * @returns {string}
 */
export const cleanTitle = (title) => Array.from(String(title ?? "").split(/\s+/).filter(Boolean).join(" ")).slice(0, TITLE_MAX).join("");

/**
 * 후보의 원본 메시지: source_message_ids 의 첫 번째(1 이상의 정수). 없으면 null(연결하지 않는다).
 * @param {{ source_message_ids?: unknown } | null | undefined} candidate
 * @returns {number | null}
 */
export function linkSourceId(candidate) {
  const first = Array.isArray(candidate?.source_message_ids) ? candidate.source_message_ids[0] : undefined;
  const id = Number(first);
  return Number.isInteger(id) && id >= 1 ? id : null;
}

/**
 * 등록한 AI 후보를 연결 입력으로 바꾼다. 원본 메시지·등록 id·제목 중 하나라도 없으면 null.
 * 일정 후보는 date/time, 할 일 후보는 due 를 날짜로 쓴다(올바른 형식만, 아니면 null — 지어내지 않는다).
 * @param {{ kind: "event" | "todo", targetId: unknown, candidate: { title?: string, date?: string | null, time?: string | null, due?: string | null, source_message_ids?: number[] } | null | undefined }} args
 * @returns {{ messageId: number, kind: "event" | "todo", targetId: string, title: string, date: string | null, time: string | null } | null}
 */
export function linkInputFromCandidate({ kind, targetId, candidate }) {
  const messageId = linkSourceId(candidate);
  const target = String(targetId ?? "").trim();
  const title = cleanTitle(candidate?.title);
  if (!messageId || !target || !title || !(kind in KIND_LABEL)) return null;
  const rawDate = kind === "todo" ? candidate?.due : candidate?.date;
  const date = isDay(rawDate) ? rawDate : null;
  const time = kind === "event" && isClock(candidate?.time) ? candidate.time : null;
  return { messageId, kind, targetId: target, title, date, time };
}

/**
 * 서버 연결 한 개를 다듬는다. 필수 값이 이상하면 null.
 * @param {object | null | undefined} raw 서버 LinkOut
 * @returns {{ id: string, room_id: string, message_id: number, kind: "event" | "todo", target_id: string, title: string, date: string | null, time: string | null, created_by: string, created_by_name: string, created_at: string, message_text: string, message_user_name: string } | null}
 */
export function normalizeLink(raw) {
  const messageId = Number(raw?.message_id);
  if (!raw?.id || !Number.isInteger(messageId) || messageId < 1 || !(raw?.kind in KIND_LABEL) || typeof raw?.title !== "string" || !raw?.created_at) return null;
  return {
    id: String(raw.id),
    room_id: String(raw.room_id ?? ""),
    message_id: messageId,
    kind: raw.kind,
    target_id: String(raw.target_id ?? ""),
    title: raw.title,
    date: raw.date ? String(raw.date) : null,
    time: raw.time ? String(raw.time) : null,
    created_by: String(raw.created_by ?? ""),
    created_by_name: String(raw.created_by_name ?? ""),
    created_at: String(raw.created_at),
    message_text: String(raw.message_text ?? ""),
    message_user_name: String(raw.message_user_name ?? ""),
  };
}

const sameTarget = (a, b) => a.message_id === b.message_id && a.kind === b.kind && a.target_id === b.target_id;

/**
 * 연결 목록 정리: 이상한 항목 제거, 같은 id 는 한 번만(나중 항목 우선), 같은 (메시지·종류·대상)은 서버 항목을 남기고, 만든 시각 최신순, 최대 LINKS_LIMIT.
 * @param {unknown} items 서버 items 또는 이미 다듬은 목록
 * @returns {ReturnType<typeof normalizeLink>[]}
 */
export function normalizeLinks(items) {
  const byId = new Map();
  for (const raw of Array.isArray(items) ? items : []) {
    const link = normalizeLink(raw);
    if (link) byId.set(link.id, link);
  }
  const all = [...byId.values()];
  const kept = all.filter((l) => !isTempLink(l) || !all.some((o) => !isTempLink(o) && sameTarget(o, l)));
  return kept.sort((a, b) => parseTime(b.created_at) - parseTime(a.created_at) || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0)).slice(0, LINKS_LIMIT);
}

/**
 * 종류로 거른 목록(최신순 유지). all 이면 전부.
 * @param {object[]} links
 * @param {"all" | "event" | "todo"} kind
 * @returns {object[]}
 */
export const filterByKind = (links, kind) => (kind === "event" || kind === "todo" ? (links ?? []).filter((l) => l.kind === kind) : (links ?? []));

/**
 * 연결을 등록 직후 미리 그려 본다(서버 응답 전). 같은 (메시지·종류·대상)이 이미 있으면 그대로 둔다.
 * @param {object[]} links
 * @param {{ messageId: number, kind: "event" | "todo", targetId: string, title: string, date: string | null, time: string | null }} input
 * @param {{ id: string, name: string } | null} me 등록한 사람
 * @param {{ text?: string, user_name?: string } | null} message 원본 메시지(목록에 있으면)
 * @param {{ nowIso: string, tempId: string, roomId?: string | null }} extra tempId 는 "tmp:" 로 시작해야 한다
 * @returns {{ links: object[], added: object | null }}
 */
export function optimisticLink(links, input, me, message, { nowIso, tempId, roomId = null }) {
  const current = normalizeLinks(links);
  const item = normalizeLink({
    id: tempId.startsWith(TEMP_PREFIX) ? tempId : `${TEMP_PREFIX}${tempId}`,
    room_id: roomId ?? "",
    message_id: input.messageId,
    kind: input.kind,
    target_id: input.targetId,
    title: input.title,
    date: input.date,
    time: input.time,
    created_by: me?.id ?? "",
    created_by_name: me?.name ?? "",
    created_at: nowIso,
    message_text: String(message?.text ?? "").slice(0, 100),
    message_user_name: message?.user_name ?? "",
  });
  if (!item || current.some((l) => sameTarget(l, item))) return { links: current, added: null };
  return { links: normalizeLinks([...current, item]), added: item };
}

export const initialLinksState = { items: [], mutSeq: 0 };

/**
 * 연결 목록 상태. seq 는 요청을 시작한 순서 번호다(useChatPins 와 같은 규칙).
 * - loaded: 조회 응답. 그 조회를 시작한 뒤에 내가 바꾼 것(mutSeq 가 더 큼)이 있으면 오래된 응답이라 버린다.
 * - add / remove: 서버 응답 전에 미리 그려 본다. confirmed: 서버 항목으로 임시 항목을 바꾼다.
 * - revert_add / revert_remove: 실패한 그 동작만 거꾸로 적용한다(목록 전체를 옛 스냅샷으로 덮지 않아 겹치는 요청이 서로 지우지 않는다).
 * @param {{ items: object[], mutSeq: number }} state
 * @param {{ type: string, seq: number, items?: object[], item?: object, tempId?: string, linkId?: string }} action
 * @returns {{ items: object[], mutSeq: number }}
 */
export function linksReducer(state, action) {
  switch (action.type) {
    case "loaded":
      return action.seq > state.mutSeq ? { ...state, items: normalizeLinks(action.items) } : state;
    case "add":
      return { items: normalizeLinks([...state.items, action.item]), mutSeq: action.seq };
    case "confirmed":
      return { items: normalizeLinks([...state.items.filter((l) => l.id !== action.tempId), action.item]), mutSeq: action.seq };
    case "revert_add":
      return { items: normalizeLinks(state.items.filter((l) => l.id !== action.tempId)), mutSeq: action.seq };
    case "remove":
      return { items: normalizeLinks(state.items.filter((l) => l.id !== String(action.linkId))), mutSeq: action.seq };
    case "revert_remove":
      return { items: normalizeLinks([...state.items, action.item]), mutSeq: action.seq };
    default:
      return state;
  }
}

/**
 * 메시지 id → 그 메시지에 걸린 연결들(최신순). 말풍선 표시용.
 * @param {object[]} links
 * @returns {Map<number, object[]>}
 */
export function linksByMessage(links) {
  const map = new Map();
  for (const link of links ?? []) {
    const list = map.get(link.message_id);
    if (list) list.push(link);
    else map.set(link.message_id, [link]);
  }
  return map;
}

/**
 * 말풍선에 붙일 등록 표시: 종류마다 한 개(일정 먼저, 할 일 다음).
 * @param {object[] | undefined} links 그 메시지의 연결들
 * @returns {{ kind: "event" | "todo", label: string }[]}
 */
export function badgesFor(links) {
  const kinds = new Set((links ?? []).map((l) => l.kind));
  return ["event", "todo"].filter((k) => kinds.has(k)).map((kind) => ({ kind, label: BADGE_LABEL[kind] }));
}

/**
 * 지울 수 있는 연결인지: 내가 만든 서버 연결만(임시 항목은 아직 지울 수 없다).
 * @param {{ id?: unknown, created_by?: string } | null | undefined} link
 * @param {string | null | undefined} myId
 * @returns {boolean}
 */
export const canDeleteLink = (link, myId) => Boolean(link) && Boolean(myId) && link.created_by === myId && !isTempLink(link);

/**
 * 날짜·시간 표시: "10월 28일 · 오후 3:00", 시간이 없으면 날짜만, 둘 다 없으면 빈 글자. 해가 다르면 연도를 붙인다.
 * @param {string | null | undefined} date YYYY-MM-DD
 * @param {string | null | undefined} time HH:MM
 * @param {Date} [now]
 * @returns {string}
 */
export function formatLinkWhen(date, time, now = new Date()) {
  const parts = [];
  if (isDay(date)) {
    const [y, m, d] = String(date).split("-").map(Number);
    parts.push(`${y === now.getFullYear() ? "" : `${y}년 `}${m}월 ${d}일`);
  }
  if (isClock(time)) {
    const [h, mi] = String(time).split(":").map(Number);
    parts.push(`${h < 12 ? "오전" : "오후"} ${h % 12 === 0 ? 12 : h % 12}:${String(mi).padStart(2, "0")}`);
  }
  return parts.join(" · ");
}

/**
 * 원본 줄: "원본: 엄마 · 본문 한 줄"(줄바꿈·연속 공백은 한 칸). 이름은 별명 우선.
 * @param {{ message_user_name?: string, message_text?: string }} link
 * @param {string} [nameOfSender] 보낸 사람 표시 이름(별명). 없으면 서버가 준 이름
 * @returns {string}
 */
export function linkSourceLine(link, nameOfSender) {
  const who = nameOfSender || link?.message_user_name || "가족";
  const text = String(link?.message_text ?? "").replace(/\s+/g, " ").trim();
  return text ? `원본: ${who} · ${text}` : `원본: ${who}`;
}

/**
 * 목록 한 줄의 접근성 라벨.
 * @param {object} link
 * @param {string} [nameOfSender]
 * @returns {string}
 */
export function linkA11yLabel(link, nameOfSender) {
  const when = formatLinkWhen(link?.date, link?.time);
  return `${KIND_LABEL[link?.kind] ?? "항목"}, ${link?.title ?? ""}${when ? `, ${when}` : ""}. ${linkSourceLine(link, nameOfSender)}. 누르면 그 메시지로 이동해요`;
}

/**
 * 다음 조회까지 기다릴 시간: 정상이면 30초, 연속 실패마다 두 배로 늘어 최대 2분(고정 메시지와 같다).
 * poll 이 false(1:1 방: 연결을 만드는 경로가 없어 처음과 시트를 열 때만 조회)면 null — 반복하지 않는다.
 * @param {number} failures
 * @param {boolean} [poll]
 * @returns {number | null} 밀리초
 */
export const nextLinkPollDelay = (failures, poll = true) => (poll ? nextPinPollDelay(failures) : null);

/**
 * 조회를 시작해도 되는지: 등록·삭제 요청이 진행 중이면 건너뛴다(오래된 응답이 낙관적 상태를 덮지 않게).
 * @param {number} pending 진행 중인 등록·삭제 요청 수
 * @returns {boolean}
 */
export const canReloadLinks = (pending) => pending === 0;

/**
 * 같은 키의 요청을 한 번만 시작한다: 이미 진행 중이면 false, 아니면 키를 넣고 true.
 * @param {Set<string>} busy
 * @param {string} key
 * @returns {boolean}
 */
export function tryBegin(busy, key) {
  if (busy.has(key)) return false;
  busy.add(key);
  return true;
}

/**
 * 삭제 실패 뒤 화면을 어떻게 할지: 404(이미 없음)는 뺀 채로 두고(keep), 403 등 나머지는 그 항목을 되살린다(revert).
 * @param {{ status?: number } | null | undefined} error
 * @returns {"keep" | "revert"}
 */
export const deleteFailureEffect = (error) => (error?.status === 404 ? "keep" : "revert");

/**
 * 할 일 id → 그 할 일을 등록한 원본 메시지 id. 같은 할 일에 연결이 여러 개면 가장 먼저 나온 것(최신순 목록의 첫 번째)을 쓴다.
 * @param {{ kind?: string, target_id?: string, message_id?: number }[] | null | undefined} links 서버 연결 목록
 * @returns {Record<string, number>}
 */
export function todoOrigins(links) {
  const map = {};
  for (const l of Array.isArray(links) ? links : []) {
    const id = String(l?.target_id ?? "");
    const messageId = Number(l?.message_id);
    if (l?.kind === "todo" && id && Number.isInteger(messageId) && messageId > 0 && !(id in map)) map[id] = messageId;
  }
  return map;
}

/**
 * 어떤 경우에도 던지지 않고 끝에 반드시 leave 를 부르는 실행기. work 가 던지면 onError 를 부르고 false 를 돌려준다(onError·leave 가 던져도 삼킨다).
 * leave 가 던지면 ref 카운터 같은 정리가 빠지므로 정리는 가장 단순한 동작만 넣는다.
 * @param {{ work: () => Promise<boolean>, onError?: (error: unknown) => void, leave?: () => void }} args
 * @returns {Promise<boolean>}
 */
export async function runGuarded({ work, onError, leave }) {
  try {
    return await work();
  } catch (e) {
    try {
      onError?.(e);
    } catch {
      // 무시
    }
    return false;
  } finally {
    try {
      leave?.();
    } catch {
      // 무시
    }
  }
}

/** 조회 겹침 규칙·조회 응답 반영 조건은 고정 메시지와 같다. */
export const linkReloadGate = reloadGate;
export const linkSettled = pinSettled;

/**
 * 요청 한 개를 구분하는 키(같은 연결을 연타해도 한 번만 보낸다).
 * @param {{ messageId: number, kind: string, targetId: string }} input
 * @returns {string}
 */
export const linkKey = (input) => `${Number(input.messageId)}:${input.kind}:${input.targetId}`;
