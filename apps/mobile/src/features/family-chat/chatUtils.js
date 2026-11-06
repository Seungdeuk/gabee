// 채팅방 순수 함수 모음(화면·훅과 분리해 시험한다). 대화 글자는 여기서 어디에도 기록하지 않는다.

import { isAlbumPhoto } from "./album";

export const MAX_TEXT = 2000;
export const POLL_BASE_MS = 3000;
export const POLL_MAX_MS = 30000;

/**
 * 서버 시각 문자열을 Date 로. 시간대 표시가 없으면 UTC 로 본다.
 * @param {string} iso
 * @returns {Date}
 */
export function parseTime(iso) {
  const text = String(iso ?? "");
  return new Date(/(Z|[+-]\d{2}:?\d{2})$/.test(text) ? text : `${text}Z`);
}

const isTemp = (m) => m.status === "sending" || m.status === "failed";
const serverId = (m) => Number(m.id);

/**
 * 메시지 목록 병합: id 기준 중복 제거 후 오름차순. 임시(전송 중·실패) 메시지는 맨 뒤에 둔다(clientId 로 구분).
 * 같은 사람이 같은 글을 보낸 "전송 중" 임시 메시지는 서버 메시지가 도착하면 하나씩 지워 중복 표시를 막는다.
 * @param {object[]} existing
 * @param {object[]} incoming
 * @returns {object[]}
 */
export function mergeMessages(existing, incoming) {
  const byId = new Map();
  const temps = new Map();
  for (const m of [...existing, ...incoming]) {
    if (isTemp(m)) temps.set(m.clientId, m);
    else byId.set(serverId(m), m);
  }
  const server = [...byId.values()].sort((a, b) => serverId(a) - serverId(b));
  const fresh = incoming.filter((m) => !isTemp(m));
  const remaining = [...temps.values()].filter((t) => {
    if (t.status !== "sending") return true;
    const i = fresh.findIndex((m) => m.user_id === t.user_id && m.text === t.text);
    if (i < 0) return true;
    fresh.splice(i, 1);
    return false;
  });
  return [...server, ...remaining];
}

/**
 * 서버에서 받은 가장 큰 메시지 id(임시 제외). 없으면 0.
 * @param {object[]} messages
 * @returns {number}
 */
export function lastId(messages) {
  return messages.reduce((max, m) => (isTemp(m) ? max : Math.max(max, serverId(m))), 0);
}

/**
 * 가장 오래된 서버 메시지 id(위로 불러올 때 before_id). 없으면 0.
 * @param {object[]} messages
 * @returns {number}
 */
export function firstId(messages) {
  const ids = messages.filter((m) => !isTemp(m)).map(serverId);
  return ids.length ? Math.min(...ids) : 0;
}

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/**
 * @param {Date} d
 * @returns {string} 예: "2026-10-23" (기기 시간대)
 */
const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * 날짜 구분선 문구.
 * @param {string} iso
 * @returns {string} 예: "2026년 10월 23일 금요일"
 */
export function formatDay(iso) {
  const d = parseTime(iso);
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${WEEKDAYS[d.getDay()]}요일`;
}

/**
 * 말풍선 옆 시각.
 * @param {string} iso
 * @returns {string} 예: "오후 3:20"
 */
export function formatTime(iso) {
  const d = parseTime(iso);
  if (Number.isNaN(d.getTime())) return "";
  const h = d.getHours();
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${h < 12 ? "오전" : "오후"} ${hour12}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * 소통 탭 목록의 시각: 오늘이면 시각, 아니면 날짜.
 * @param {string} iso
 * @param {Date} [now]
 * @returns {string}
 */
export function formatListTime(iso, now = new Date()) {
  const d = parseTime(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (dayKey(d) === dayKey(now)) return formatTime(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/**
 * 같은 날짜끼리 묶는다(날짜 구분선용).
 * @param {object[]} messages 오름차순
 * @returns {{ key: string, label: string, messages: object[] }[]}
 */
export function groupByDay(messages) {
  const groups = [];
  for (const m of messages) {
    const key = dayKey(parseTime(m.created_at));
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.messages.push(m);
    else groups.push({ key, label: formatDay(m.created_at), messages: [m] });
  }
  return groups;
}

/**
 * 같은 사람이 이어서 말하면 이름(과 아바타)을 생략한다.
 * @param {object | undefined} prev 바로 앞 메시지(같은 날짜일 때만 넘긴다)
 * @param {object} cur
 * @returns {boolean}
 */
export function shouldShowName(prev, cur) {
  return !prev || prev.deleted || prev.user_id !== cur.user_id; // 앞이 지운 줄(가운데 안내)이면 누가 보냈는지 이름을 보인다
}

/**
 * 시각을 보여 줄지: 같은 사람이 같은 분 안에 이어서 보내면 마지막 메시지에만 보여 준다.
 * @param {object} cur
 * @param {object | undefined} next 바로 다음 메시지(같은 날짜일 때만 넘긴다)
 * @returns {boolean}
 */
export function shouldShowTime(cur, next) {
  if (!next || next.deleted || next.user_id !== cur.user_id) return true; // 다음이 지운 줄이면 이 메시지의 시각을 보인다
  if (next.status === "sending" || next.status === "failed") return true;
  const a = parseTime(cur.created_at);
  const b = parseTime(next.created_at);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return true;
  return a.getFullYear() !== b.getFullYear() || a.getMonth() !== b.getMonth() || a.getDate() !== b.getDate() || a.getHours() !== b.getHours() || a.getMinutes() !== b.getMinutes();
}

/**
 * "여기까지 읽었습니다" 구분선을 놓을 자리: 구분선 바로 아래에 올 서버 메시지의 id. 없으면 null.
 * 기준(lastRead) 보다 id 가 큰 첫 서버 메시지 앞이다(임시·실패·가비 개인 답 제외, 삭제된 메시지는 센다).
 * 그 이후 서버 메시지 중 내가 보낸 것이 아닌 것이 하나도 없거나, 안 읽은 수가 0 이거나, 기준이 없으면 null.
 * 기준이 불러온 목록보다 오래돼 목록 전체가 안 읽은 쪽이면 가장 오래된 메시지가 첫 안 읽은 메시지라 맨 위에 놓인다.
 * @param {object[]} messages 오름차순(chat.messages)
 * @param {{ lastRead: number, unread: number } | null | undefined} baseline 입장 시점의 읽음 위치와 안 읽은 수
 * @param {string | null | undefined} myId
 * @returns {number | null}
 */
export function unreadDividerId(messages, baseline, myId) {
  if (!baseline || !(baseline.unread > 0)) return null;
  const lastRead = Number(baseline.lastRead) || 0;
  const server = messages.filter((m) => !m.clientId && !m.localNote && !isTemp(m) && Number.isFinite(serverId(m)));
  const first = server.findIndex((m) => serverId(m) > lastRead);
  if (first < 0) return null;
  if (!server.slice(first).some((m) => !myId || m.user_id !== myId)) return null;
  return serverId(server[first]);
}

/**
 * 같은 사람이 같은 묶음 번호(batch_id)로 연달아 올린 사진을 한 덩어리로 모은다(2장 이상일 때만). 그 외 메시지는 한 개씩 그대로다.
 * @param {object[]} messages 같은 날짜의 메시지(오름차순)
 * @returns {object[][]} 덩어리 목록(앨범이면 2개 이상)
 */
function runsOf(messages) {
  const runs = [];
  for (const m of messages) {
    const last = runs[runs.length - 1];
    const prev = last?.[last.length - 1];
    if (prev && isAlbumPhoto(m) && isAlbumPhoto(prev) && prev.user_id === m.user_id && prev.attachment.batch_id === m.attachment.batch_id) last.push(m);
    else runs.push([m]);
  }
  return runs;
}

/**
 * 줄 하나가 이 서버 메시지를 담고 있는지(앨범 안에 숨은 사진도 센다). 검색·고정·답장 원본으로 이동할 때 줄을 찾는 데 쓴다.
 * @param {{ type: string, message?: object, album?: object[] }} item buildItems 의 줄
 * @param {number | string} messageId
 * @returns {boolean}
 */
export function itemHasMessage(item, messageId) {
  if (item?.type !== "message") return false;
  const id = String(messageId);
  if (item.album) return item.album.some((m) => String(m.id) === id);
  return String(item.message.id) === id;
}

/**
 * FlatList 에 넣을 줄 목록: 날짜 구분선, (있으면) 안 읽음 구분선, 메시지(같은 묶음의 사진은 album 이 있는 한 줄).
 * 안 읽음 구분선은 dividerBeforeId 메시지 바로 앞에 끼우므로 그 메시지가 날짜의 첫 줄이면 날짜 줄 다음에 온다(앨범 안이면 앨범 앞).
 * 앨범 줄의 message 는 마지막 사진이다(시각·읽음·반응 기준). 이름은 앨범 앞 메시지, 시각은 앨범 뒤 메시지로 정하고 key 는 첫 사진이다.
 * @param {object[]} messages 오름차순
 * @param {{ dividerBeforeId?: number | null }} [options] dividerBeforeId: unreadDividerId 의 결과
 * @returns {({ type: "day", key: string, label: string } | { type: "unread", key: string } | { type: "message", key: string, message: object, album?: object[], showName: boolean, showTime: boolean })[]}
 */
export function buildItems(messages, { dividerBeforeId = null } = {}) {
  const items = [];
  let dividerDone = dividerBeforeId == null;
  for (const g of groupByDay(messages)) {
    items.push({ type: "day", key: `day-${g.key}`, label: g.label });
    const runs = runsOf(g.messages);
    runs.forEach((run, i) => {
      const first = run[0];
      const last = run[run.length - 1];
      let justAfterDivider = false;
      if (!dividerDone && run.some((m) => !m.clientId && !m.localNote && serverId(m) === dividerBeforeId)) {
        items.push({ type: "unread", key: "unread-divider" });
        dividerDone = true;
        justAfterDivider = true;
      }
      const prev = runs[i - 1]?.[runs[i - 1].length - 1];
      const next = runs[i + 1]?.[0];
      items.push({
        type: "message",
        key: `m-${first.clientId ?? first.id}`,
        message: last,
        ...(run.length > 1 ? { album: run } : {}),
        showName: justAfterDivider || shouldShowName(prev, first), // 구분선 바로 아래 메시지는 이름을 다시 보인다
        showTime: shouldShowTime(last, next),
      });
    });
  }
  return items;
}

/**
 * 보낼 글 다듬기(앞뒤 공백 제거).
 * @param {string} text
 * @returns {string}
 */
export const trimDraft = (text) => String(text ?? "").trim();

/**
 * 보낼 수 있는 글인지: 공백만이면 안 되고 2000자를 넘으면 안 된다.
 * @param {string} text
 * @returns {boolean}
 */
export function canSend(text) {
  const t = trimDraft(text);
  return t.length > 0 && t.length <= MAX_TEXT;
}

/**
 * 소통 탭 미리보기(한 줄). 내 글이면 "나: " 를 붙인다.
 * @param {object | null | undefined} message
 * @param {string | null} [myId]
 * @returns {string}
 */
export function previewText(message, myId = null) {
  if (!message) return "아직 대화가 없어요";
  if (message.deleted) return "삭제된 메시지입니다";
  const body = String(message.text ?? "").replace(/\s+/g, " ").trim() || (message.attachment ? (message.attachment.kind === "file" ? "파일" : "사진") : "");
  return myId && message.user_id === myId ? `나: ${body}` : body;
}

/**
 * 다음 폴링까지 기다릴 시간: 정상이면 3초, 메시지 조회가 연속 실패할 때마다 두 배로 늘어 최대 30초(읽음 조회 실패는 반영하지 않는다).
 * @param {number} failures 메시지 조회 연속 실패 횟수
 * @returns {number} 밀리초
 */
export function nextPollDelay(failures) {
  if (!failures || failures < 1) return POLL_BASE_MS;
  return Math.min(POLL_MAX_MS, POLL_BASE_MS * 2 ** failures);
}

const BY_CODE = {
  network_error: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요",
  api_not_configured: "서버 주소가 설정되지 않아 대화를 불러올 수 없어요",
  no_group: "가족을 먼저 만들거나 참여해 주세요",
  not_member: "이 가족의 구성원이 아니에요",
  token_required: "로그인이 필요해요",
  token_invalid: "로그인이 필요해요",
  session_expired: "로그인이 만료됐어요. 다시 로그인해 주세요",
  invalid_member: "같은 가족 구성원과만 1:1 대화를 할 수 있어요",
  not_found: "대화방을 찾을 수 없어요",
  photo_too_large: "사진이 너무 커요. 더 작은 사진을 골라 주세요",
  invalid_image: "이 사진은 보낼 수 없어요. JPEG·PNG·WebP 사진(2500만 화소 이하)을 골라 주세요",
  too_many_uploads: "사진을 너무 자주 보냈어요. 잠시 후 다시 해 주세요",
  photo_busy: "지금 사진을 처리하는 요청이 많아요. 잠시 후 다시 해 주세요",
};

/**
 * 채팅 오류를 사용자 문장으로(대화 내용은 넣지 않는다).
 * @param {{ code?: string } | null | undefined} error
 * @returns {string}
 */
export function roomErrorMessage(error) {
  return BY_CODE[error?.code] ?? "잠시 문제가 생겼어요. 다시 시도해 주세요";
}

/**
 * 사진 보내기 오류를 사용자 문장으로. 코드가 없어도 상태(413 크기 초과, 429 너무 잦음)로 알아본다. 사진·대화 내용은 넣지 않는다.
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @returns {string}
 */
export function photoSendErrorMessage(error) {
  if (!error?.code || !BY_CODE[error.code]) {
    if (error?.status === 413) return BY_CODE.photo_too_large;
    if (error?.status === 429) return BY_CODE.too_many_uploads;
  }
  return roomErrorMessage(error);
}

/**
 * 대화 검색 오류를 사용자 문장으로. 서버 코드 이름에 기대지 않고 상태로도 알아본다(429 너무 잦음, 422 검색어 길이). 검색어·결과 글자는 넣지 않는다.
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @returns {string}
 */
export function searchErrorMessage(error) {
  if (error?.status === 429) return "검색을 너무 자주 했어요. 잠시 후 다시 해 주세요";
  if (error?.status === 422) return "검색어는 1자에서 100자 사이로 입력해 주세요";
  return roomErrorMessage(error);
}

/**
 * 검색 결과 위치로 이동하다 실패했을 때의 문장(그 방의 메시지가 아니거나 없는 경우 등).
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @returns {string}
 */
export function focusErrorMessage(error) {
  if (error?.code === "invalid_message" || error?.status === 400 || error?.status === 404) return "그 메시지를 찾지 못해 최근 대화를 보여 드려요";
  return roomErrorMessage(error);
}

/**
 * 가족이 없다는 응답(404 또는 no_group)인지.
 * @param {{ status?: number, code?: string } | null | undefined} error
 * @returns {boolean}
 */
export const isNoGroup = (error) => error?.status === 404 || error?.code === "no_group";

/**
 * 내 메시지를 아직 읽지 않은 사람 수. 내가 보낸 서버 메시지(임시·실패 제외)에만 값이 있고, 그 외에는 0(표시 안 함).
 * 서버 read-states 가 현재 구성원 전원(합류 기준선 포함)을 주므로 그 user_id 만으로 센다: 나를 제외하고 last_read_message_id 가 메시지 id 보다 작은 사람.
 * 읽음 상태를 한 번도 못 받았으면(null) 0 이라 숫자를 숨긴다.
 * @param {object} message
 * @param {{ id: string } | string | null | undefined} me 나(객체 또는 id)
 * @param {{ user_id: string, last_read_message_id: number }[] | null | undefined} readStates
 * @returns {number}
 */
export function unreadCount(message, me, readStates) {
  const myId = typeof me === "string" ? me : me?.id;
  if (!Array.isArray(readStates) || !message || !myId || message.user_id !== myId || isTemp(message)) return 0;
  const id = serverId(message);
  if (!Number.isFinite(id)) return 0;
  return readStates.filter((s) => s.user_id !== myId && (Number(s.last_read_message_id) || 0) < id).length;
}

export const READ_SKIP_MAX_TICKS = 10;

/**
 * 읽음 조회를 이번 틱에 할지: 실패가 없으면 매 틱, 연속 실패 n 번이면 2^n 틱(최대 10틱)마다 한 번.
 * @param {number} ticksSinceLast 마지막 조회 시도 뒤 지난 틱 수(이번 틱 포함)
 * @param {number} failures 읽음 조회 연속 실패 횟수
 * @returns {boolean}
 */
export function readStatesDue(ticksSinceLast, failures) {
  if (!failures || failures < 1) return true;
  return Number(ticksSinceLast) >= Math.min(READ_SKIP_MAX_TICKS, 2 ** failures);
}

/**
 * 화면을 떠날 때 지금 바로 올려야 할 읽음 id. 대기 중인 값이 올린 값보다 크고 같은 id 를 보내는 중이 아닐 때만, 없으면 0.
 * @param {number} target 목록의 가장 큰 서버 메시지 id
 * @param {number} lastMarked 올렸거나 서버가 반영한 값
 * @param {number} sendingId 지금 보내는 중인 id(없으면 0)
 * @returns {number}
 */
export function flushTarget(target, lastMarked, sendingId) {
  const t = Number(target) || 0;
  return t >= 1 && t > Number(lastMarked || 0) && t !== Number(sendingId || 0) ? t : 0;
}

/**
 * 읽음 위치를 서버에 올려야 하는지: 보이는 상태이고, 목록의 가장 큰 서버 id 가 지금까지 올린 값보다 클 때만.
 * @param {number} current 목록의 가장 큰 서버 메시지 id(임시 제외)
 * @param {number} lastMarked 지금까지 올린(또는 서버가 이미 반영한) 값
 * @param {boolean} enabled 화면이 보이고 앱이 앞에 있는지
 * @returns {boolean}
 */
export const shouldMarkRead = (current, lastMarked, enabled) => Boolean(enabled) && Number(current) >= 1 && Number(current) > Number(lastMarked || 0);

/**
 * 입력칸에서 Enter 로 보내야 하는지: 웹(키보드 연결)에서 Shift 없이 Enter 를 눌렀고 한글 등 글자 조합 중이 아닐 때만.
 * Shift+Enter 는 줄바꿈, 폰 화면 키보드(네이티브)의 Enter 도 줄바꿈을 유지한다.
 * @param {{ key?: string, shiftKey?: boolean, isComposing?: boolean, keyCode?: number } | null | undefined} event 키 이벤트의 nativeEvent
 * @param {string} platform Platform.OS ("web" | "ios" | "android")
 * @returns {boolean}
 */
export function shouldSendOnEnter(event, platform) {
  if (platform !== "web" || !event) return false;
  if (event.key !== "Enter" || event.shiftKey) return false;
  if (event.isComposing || event.keyCode === 229) return false; // 한글·일본어 입력 조합 중의 Enter 는 글자 확정용
  return true;
}

/**
 * 게시판 오류(올리기·내리기·숨기기)를 사용자 문장으로(메시지 글자는 넣지 않는다). 서버 코드 이름에 기대지 않고 상태로도 알아본다.
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @param {"pin" | "unpin" | "hide" | "show"} [action] 올리기가 아닌 동작 중 404 는 "이미 내려갔거나 볼 수 없는 공지"다(서버가 공지 없음과 방 접근 불가를 같은 404 로 준다)
 * @returns {string}
 */
export function pinErrorMessage(error, action = "pin") {
  if (error?.code === "not_pinnable") return "사진이나 빈 메시지는 게시판에 올릴 수 없어요";
  if (error?.code === "invalid_message") return "이 대화방의 메시지가 아니라 게시판에 올릴 수 없어요";
  if (error?.status === 429) return "너무 자주 바꿨어요. 잠시 뒤에 다시 해 주세요";
  if (error?.code === "pin_changed" || error?.status === 409) return "다른 사람이 방금 바꿨어요. 다시 확인해 주세요";
  if (error?.status === 404) return action !== "pin" ? "이미 내려갔거나 볼 수 없는 공지예요" : "대화방을 찾을 수 없거나 권한이 없어요";
  return roomErrorMessage(error);
}

/**
 * 일정·할 일 연결 오류를 사용자 문장으로(제목·본문은 넣지 않는다). 상태로도 알아본다(403 만든 사람만, 404, 429).
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @param {"create" | "delete"} [action]
 * @returns {string}
 */
export function linkErrorMessage(error, action = "create") {
  if (error?.code === "invalid_message") return "이 메시지는 연결할 수 없어요";
  if (error?.code === "invalid_target") return "연결할 일정·할 일을 찾을 수 없어요";
  if (error?.code === "too_many_links") return "연결이 너무 많아요";
  if (error?.status === 403 || error?.code === "forbidden") return "만든 사람만 지울 수 있어요";
  if (error?.status === 429) return "너무 자주 했어요. 잠시 뒤에 다시 해 주세요";
  if (error?.status === 404) return action === "delete" ? "이미 지워진 연결이에요" : "대화방을 찾을 수 없거나 권한이 없어요";
  return roomErrorMessage(error);
}
