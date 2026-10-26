// 고정 메시지(공지)의 순수 함수(화면·네트워크와 분리해 시험한다). 메시지 글자·고정 내용은 어디에도 기록하지 않는다.
import { formatTime, parseTime } from "./chatUtils";

/** 방당 고정 가능한 최대 개수(서버 규칙과 같다). 넘으면 가장 오래된 고정이 풀린다. */
export const MAX_PINS = 2;

/** 서버가 고정 본문을 이 길이까지만 돌려준다(낙관적 항목도 같은 길이로 맞춘다). */
export const PIN_TEXT_MAX = 200;

export const REPLACED_NOTICE = "가장 오래된 고정이 해제됐어요";
export const PINNED_NOTICE = "공지로 고정했어요";
export const ALREADY_PINNED_NOTICE = "이미 고정된 메시지예요";
export const UNPINNED_NOTICE = "고정을 해제했어요";
export const NO_PINS_NOTICE = "고정된 메시지가 없어요";
export const BUSY_NOTICE = "처리 중이에요";
export const COPIED_NOTICE = "복사했어요";
export const COPY_FAILED_NOTICE = "복사하지 못했어요";

/**
 * 서버에 저장된 메시지인지(임시: 전송 중·실패 제외, 숫자 id 가 있어야 한다).
 * @param {{ id?: unknown, clientId?: string, status?: string } | null | undefined} message
 * @returns {boolean}
 */
const isSaved = (message) => Boolean(message) && !message.clientId && message.status !== "sending" && message.status !== "failed" && Number.isInteger(Number(message.id)) && Number(message.id) >= 1;

/**
 * 고정 메뉴를 보여도 되는 메시지인지: 서버에 저장된 텍스트 메시지(사진이 없고 글이 있는 것)만.
 * @param {{ id?: unknown, text?: string, clientId?: string, status?: string, attachment?: object | null } | null | undefined} message
 * @returns {boolean}
 */
export const canPin = (message) => isSaved(message) && !message.attachment && String(message.text ?? "").trim().length > 0;

/**
 * 고정 항목 한 개를 다듬는다. 필수 값이 이상하면 null(지어내지 않는다).
 * @param {object | null | undefined} raw 서버 PinItem
 * @returns {{ message_id: number, text: string, text_truncated: boolean, user_id: string, user_name: string, created_at: string, pinned_by: string, pinned_by_name: string, pinned_at: string } | null}
 */
export function normalizePin(raw) {
  const id = Number(raw?.message_id);
  if (!Number.isInteger(id) || id < 1 || typeof raw?.text !== "string" || !raw?.pinned_at) return null;
  return {
    message_id: id,
    text: raw.text,
    text_truncated: Boolean(raw.text_truncated),
    user_id: String(raw.user_id ?? ""),
    user_name: String(raw.user_name ?? ""),
    created_at: String(raw.created_at ?? ""),
    pinned_by: String(raw.pinned_by ?? ""),
    pinned_by_name: String(raw.pinned_by_name ?? ""),
    pinned_at: String(raw.pinned_at),
  };
}

/**
 * 고정 목록 정리: 이상한 항목 제거, 같은 메시지는 한 번만(나중 항목 우선), 고정 시각 최신순, 최대 2개.
 * @param {unknown} items 서버 items 또는 이미 다듬은 목록
 * @returns {ReturnType<typeof normalizePin>[]}
 */
export function normalizePins(items) {
  const byId = new Map();
  for (const raw of Array.isArray(items) ? items : []) {
    const pin = normalizePin(raw);
    if (pin) byId.set(pin.message_id, pin);
  }
  return [...byId.values()]
    .sort((a, b) => parseTime(b.pinned_at) - parseTime(a.pinned_at) || b.message_id - a.message_id)
    .slice(0, MAX_PINS);
}

/**
 * 고정된 메시지 id 모음.
 * @param {{ message_id: number }[]} pins
 * @returns {Set<number>}
 */
export const pinnedIdSet = (pins) => new Set((pins ?? []).map((p) => p.message_id));

/**
 * 메시지를 고정한 결과를 미리 그려 본다(서버 응답 전). 이미 있으면 그대로 두고, 최대 개수를 넘으면 가장 오래된 고정이 빠진다.
 * @param {object[]} pins
 * @param {{ id: number|string, text: string, user_id: string, user_name: string, created_at: string }} message
 * @param {{ id: string, name: string } | null} me 고정하는 사람
 * @param {string} nowIso 고정 시각
 * @returns {{ pins: object[], replacedId: number | null }}
 */
export function optimisticPin(pins, message, me, nowIso) {
  const current = normalizePins(pins);
  const id = Number(message.id);
  if (current.some((p) => p.message_id === id)) return { pins: current, replacedId: null };
  const text = String(message.text ?? "");
  // 기기 시계가 서버보다 늦어도 새 고정이 맨 앞(최신)에 오도록, 기존 가장 최근 고정보다 항상 나중 시각을 준다
  const newest = current.reduce((max, p) => Math.max(max, parseTime(p.pinned_at).getTime() || 0), 0);
  const at = Math.max(parseTime(nowIso).getTime() || 0, newest + 1);
  const item = {
    message_id: id,
    text: text.slice(0, PIN_TEXT_MAX),
    text_truncated: text.length > PIN_TEXT_MAX,
    user_id: message.user_id,
    user_name: message.user_name,
    created_at: message.created_at,
    pinned_by: me?.id ?? "",
    pinned_by_name: me?.name ?? "",
    pinned_at: new Date(at).toISOString(),
  };
  const next = normalizePins([...current, item]);
  const kept = pinnedIdSet(next);
  const dropped = current.find((p) => !kept.has(p.message_id));
  return { pins: next, replacedId: dropped ? dropped.message_id : null };
}

/**
 * 고정 해제를 미리 그려 본다.
 * @param {object[]} pins
 * @param {number|string} messageId
 * @returns {object[]}
 */
export const optimisticUnpin = (pins, messageId) => normalizePins((pins ?? []).filter((p) => p.message_id !== Number(messageId)));

/**
 * 고정 요청의 서버 응답을 목록에 반영한다: 돌려준 항목을 넣고, 자동 해제된 메시지(replaced_message_id)는 뺀다.
 * @param {object[]} pins
 * @param {{ item?: object, replaced_message_id?: number | null } | null | undefined} result
 * @returns {object[]}
 */
export function applyPinResult(pins, result) {
  const replaced = result?.replaced_message_id != null ? Number(result.replaced_message_id) : null;
  const rest = (pins ?? []).filter((p) => p.message_id !== replaced);
  return normalizePins(result?.item ? [...rest, result.item] : rest);
}

/**
 * 고정 요청 뒤에 보여 줄 안내 문구.
 * @param {{ replaced_message_id?: number | null, already_pinned?: boolean } | null | undefined} result
 * @returns {string}
 */
export function pinResultNotice(result) {
  if (result?.already_pinned) return ALREADY_PINNED_NOTICE;
  if (result?.replaced_message_id != null) return `${PINNED_NOTICE}. ${REPLACED_NOTICE}`;
  return PINNED_NOTICE;
}

export const initialPinsState = { items: [], mutSeq: 0 };

/**
 * 고정 목록 상태. seq 는 요청을 시작한 순서 번호다.
 * - loaded: 조회 응답. 그 조회를 시작한 뒤에 내가 바꾼 것(mutSeq 가 더 큼)이 있으면 오래된 응답이라 버린다.
 * - pin / unpin: 서버 응답 전에 미리 그려 본다. confirmed: 서버 응답 반영.
 * - revert_pin / revert_unpin: 실패한 그 동작만 거꾸로 적용한다(목록 전체를 옛 스냅샷으로 덮지 않아 겹치는 요청이 서로 지우지 않는다).
 * @param {{ items: object[], mutSeq: number }} state
 * @param {{ type: string, seq: number, items?: object[], restore?: object | null, item?: object, message?: object, me?: object | null, now?: string, messageId?: number|string, result?: object }} action
 * @returns {{ items: object[], mutSeq: number }}
 */
export function pinsReducer(state, action) {
  switch (action.type) {
    case "loaded":
      return action.seq > state.mutSeq ? { ...state, items: normalizePins(action.items) } : state;
    case "pin":
      return { items: optimisticPin(state.items, action.message, action.me, action.now).pins, mutSeq: action.seq };
    case "unpin":
      return { items: optimisticUnpin(state.items, action.messageId), mutSeq: action.seq };
    case "confirmed":
      return { items: applyPinResult(state.items, action.result), mutSeq: action.seq };
    case "revert_pin": // 고정 실패: 그 고정만 빼고, 교체로 빠졌던 항목(restore)을 되살린다. 다른 요청이 바꾼 항목은 건드리지 않는다
      return { items: normalizePins([...state.items.filter((p) => p.message_id !== Number(action.messageId)), ...(action.restore ? [action.restore] : [])]), mutSeq: action.seq };
    case "revert_unpin": // 해제 실패: 그 항목만 되살린다
      return { items: normalizePins([...state.items, action.item]), mutSeq: action.seq };
    default:
      return state;
  }
}

/** 고정 목록을 다시 조회하는 간격(밀리초). 메시지 폴링(3초)보다 느슨하게 한다. */
export const PIN_POLL_MS = 30000;
export const PIN_POLL_MAX_MS = 120000;

/**
 * 다음 조회까지 기다릴 시간: 정상이면 30초, 연속 실패마다 두 배로 늘어 최대 2분.
 * @param {number} failures 연속 실패 횟수
 * @returns {number} 밀리초
 */
export function nextPinPollDelay(failures) {
  if (!failures || failures < 1) return PIN_POLL_MS;
  return Math.min(PIN_POLL_MAX_MS, PIN_POLL_MS * 2 ** failures);
}

/**
 * 고정 바에 보일 줄: 펼쳤으면 전부(최대 2개), 접었으면 가장 최근 1개.
 * @param {object[]} pins 최신순 목록
 * @param {boolean} expanded
 * @returns {{ rows: object[], canToggle: boolean, hidden: number }} canToggle 은 접고 펼칠 수 있는지(고정이 2개 이상일 때만)
 */
export function pinBarView(pins, expanded) {
  const list = normalizePins(pins);
  const rows = expanded ? list : list.slice(0, 1);
  return { rows, canToggle: list.length > 1, hidden: list.length - rows.length };
}

/**
 * 한 줄로 보일 고정 본문(줄바꿈·연속 공백을 한 칸으로).
 * @param {{ text?: string }} pin
 * @returns {string}
 */
export const pinLine = (pin) => String(pin?.text ?? "").replace(/\s+/g, " ").trim();

/**
 * 고정한 사람·시각 보조 줄: "엄마님이 10월 24일 오후 3:20 에 고정" 대신 "엄마 고정 · 10월 24일 오후 3:20".
 * @param {{ pinned_by_name?: string, pinned_at?: string }} pin
 * @param {(userId: string) => string | undefined} [nameOf] 사용자 id → 표시 이름(별명). 모르면 서버가 준 이름
 * @returns {string}
 */
export function pinMeta(pin, nameOf) {
  const who = nameOf?.(pin?.pinned_by) || pin?.pinned_by_name || "가족";
  const d = parseTime(pin?.pinned_at);
  if (Number.isNaN(d.getTime())) return `${who} 고정`;
  return `${who} 고정 · ${d.getMonth() + 1}월 ${d.getDate()}일 ${formatTime(pin.pinned_at)}`;
}

/**
 * 고정 한 줄의 접근성 라벨.
 * @param {object} pin
 * @param {(userId: string) => string | undefined} [nameOf]
 * @returns {string}
 */
export function pinA11yLabel(pin, nameOf) {
  const author = nameOf?.(pin?.user_id) || pin?.user_name || "가족";
  return `고정 메시지, ${author}: ${pinLine(pin)}. ${pinMeta(pin, nameOf)}. 누르면 그 메시지로 이동해요`;
}

/**
 * 고정 바 항목을 눌렀을 때: 라이브이고 그 메시지가 이미 목록에 있으면 스크롤+강조만(scroll), 아니면 그 위치 창을 불러온다(focus).
 * @param {{ messages: object[], messageId: number|string, focusing: boolean }} args focusing 은 과거 창을 보는 중인지
 * @returns {"scroll" | "focus"}
 */
export function pinTapAction({ messages, messageId, focusing }) {
  if (focusing) return "focus";
  const id = Number(messageId);
  const found = (messages ?? []).some((m) => !m.clientId && Number(m.id) === id);
  return found ? "scroll" : "focus";
}

/**
 * 말풍선 글자를 선택할 수 있게 둘지. 길게 누르기 메뉴가 있는 네이티브는 선택을 꺼서 길게 누르기가 메뉴를 열게 한다(웹은 유지).
 * prop 과 style(userSelect)을 같이 맞춰야 한다 — 스타일의 userSelect 가 prop 을 이긴다.
 * @param {{ canAct: boolean, os: string }} args
 * @returns {boolean}
 */
export const bubbleSelectable = ({ canAct, os }) => !canAct || os === "web";

/**
 * 고정 목록 조회 겹침 규칙: 조회 중에 또 요청되면 건너뛰되 "끝나면 한 번 더" 표시를 남긴다.
 * @param {{ inFlight: boolean, again: boolean }} gate
 * @param {"request" | "done"} event
 * @returns {{ gate: { inFlight: boolean, again: boolean }, run: boolean }} run 은 지금 조회를 시작해야 하는지(done 이면 다시 조회해야 하는지)
 */
export function reloadGate(gate, event) {
  if (event === "request") return gate.inFlight ? { gate: { inFlight: true, again: true }, run: false } : { gate: { inFlight: true, again: false }, run: true };
  return { gate: { inFlight: false, again: false }, run: gate.again };
}

/**
 * 말풍선 글자 스타일 배열. 선택을 끌 때 noSelect(userSelect:none)를 맨 뒤에 둬서 base 의 userSelect 를 덮는다(RN 에서는 스타일이 selectable prop 을 이긴다).
 * @param {{ selectable: boolean, base: object, photo?: object | null, noSelect: object }} args
 * @returns {object[]}
 */
export const bubbleTextStyle = ({ selectable, base, photo = null, noSelect }) => [base, photo, !selectable ? noSelect : null].filter(Boolean);

/**
 * 고정·해제 요청이 실패했을 때 화면을 어떻게 할지: 해제 중 404(이미 풀려 있음)는 미리 뺀 상태를 그대로 두고(keep), 나머지는 그 동작을 거꾸로 적용한다(revert).
 * @param {"pin" | "unpin"} action
 * @param {{ status?: number } | null | undefined} error
 * @returns {"keep" | "revert"}
 */
export const failureEffect = (action, error) => (action === "unpin" && error?.status === 404 ? "keep" : "revert");

/**
 * 조회 응답을 반영하거나 요청 뒤 서버 맞춤 조회를 해도 되는지: 화면이 살아 있고 진행 중인 고정·해제 요청이 없을 때만.
 * @param {{ pending: number, alive: boolean }} args
 * @returns {boolean}
 */
export const pinSettled = ({ pending, alive }) => alive && pending === 0;
