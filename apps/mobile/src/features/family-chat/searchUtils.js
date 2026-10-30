// 대화 검색 순수 함수 모음(화면·훅과 분리해 시험한다). 검색어·결과 글자는 여기서 어디에도 기록하지 않는다.
import { formatTime, parseTime } from "./chatUtils";

export const SEARCH_DEBOUNCE_MS = 300;
export const SEARCH_MAX_QUERY = 100;
export const SEARCH_PAGE = 20;
export const FOCUS_PAGE = 50;

/**
 * 검색어를 공백 기준 낱말로 나눈다(앞뒤 공백·빈 낱말 제거, 대소문자만 다른 중복 제거). 서버도 모든 낱말이 포함된 글만 돌려준다.
 * @param {string | null | undefined} q
 * @returns {string[]}
 */
export function searchTerms(q) {
  const seen = new Set();
  const terms = [];
  for (const part of String(q ?? "").split(/\s+/)) {
    const key = part.toLowerCase();
    if (!part || seen.has(key)) continue;
    seen.add(key);
    terms.push(part);
  }
  return terms;
}

/**
 * 서버에 보낼 검색어: 낱말을 한 칸 공백으로 이어 붙이고 100자로 자른다. 낱말이 없으면 빈 문자열(검색하지 않음).
 * @param {string | null | undefined} q
 * @returns {string}
 */
export const normalizeQuery = (q) => searchTerms(q).join(" ").slice(0, SEARCH_MAX_QUERY).trim();

/**
 * 이 검색어로 서버를 불러야 하는지: 낱말이 있고, 직전에 이미 부른 검색어와 같지 않을 때만.
 * @param {string} normalized normalizeQuery 결과
 * @param {string} lastRequested 직전에 요청한 검색어(없으면 빈 문자열)
 * @returns {boolean}
 */
export const shouldRunSearch = (normalized, lastRequested) => Boolean(normalized) && normalized !== (lastRequested ?? "");

/**
 * 응답이 아직 유효한지(그 뒤에 새 요청이 시작되지 않았는지). 오래된 응답은 버린다.
 * @param {number} requestSeq 요청을 보낼 때의 번호
 * @param {number} currentSeq 지금 가장 최근 요청 번호
 * @returns {boolean}
 */
export const isLatestRequest = (requestSeq, currentSeq) => requestSeq === currentSeq;

/**
 * 글에서 검색어 낱말이 들어 있는 구간. 대소문자는 구분하지 않고, 겹치거나 맞닿은 구간은 하나로 합친다.
 * 한글은 조합된 글자 그대로 비교한다(자모 분리 없음).
 * @param {string} text
 * @param {string[]} terms
 * @returns {{ start: number, end: number }[]} 시작(포함)~끝(미포함), 오름차순
 */
export function highlightRanges(text, terms) {
  const s = String(text ?? "");
  const list = (Array.isArray(terms) ? terms : []).filter(Boolean);
  if (!s || list.length === 0) return [];
  const lower = s.toLowerCase();
  const fold = lower.length === s.length; // 소문자로 바꿔 길이가 달라지는 드문 글자가 있으면 위치가 어긋나므로 원문 그대로 비교한다
  const hay = fold ? lower : s;
  const raw = [];
  for (const term of list) {
    const needle = fold ? term.toLowerCase() : term;
    if (!needle) continue;
    let from = 0;
    while (from <= hay.length - needle.length) {
      const i = hay.indexOf(needle, from);
      if (i < 0) break;
      raw.push([i, i + needle.length]);
      from = i + needle.length;
    }
  }
  raw.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged = [];
  for (const [start, end] of raw) {
    const last = merged[merged.length - 1];
    if (last && start <= last.end) last.end = Math.max(last.end, end);
    else merged.push({ start, end });
  }
  return merged;
}

/**
 * 글을 강조할 부분과 아닌 부분으로 나눈다.
 * @param {string} text
 * @param {string[]} terms
 * @returns {{ text: string, hit: boolean }[]}
 */
export function splitHighlight(text, terms) {
  const s = String(text ?? "");
  const ranges = highlightRanges(s, terms);
  if (ranges.length === 0) return s ? [{ text: s, hit: false }] : [];
  const parts = [];
  let at = 0;
  for (const { start, end } of ranges) {
    if (start > at) parts.push({ text: s.slice(at, start), hit: false });
    parts.push({ text: s.slice(start, end), hit: true });
    at = end;
  }
  if (at < s.length) parts.push({ text: s.slice(at), hit: false });
  return parts;
}

/**
 * 미리보기 글: 줄바꿈을 공백으로 줄이고, 첫 일치가 너무 뒤에 있으면 앞을 "…" 로 잘라 일치 부분이 보이게 한다.
 * @param {string} text
 * @param {string[]} terms
 * @param {number} [lead] 일치 앞에 남길 글자 수
 * @returns {string}
 */
export function previewSnippet(text, terms, lead = 24) {
  const flat = String(text ?? "").replace(/\s+/g, " ").trim();
  const first = highlightRanges(flat, terms)[0];
  if (!first || first.start <= lead + 16) return flat;
  return `…${flat.slice(first.start - lead)}`;
}

const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/**
 * 검색 결과의 시각: 오늘이면 시각, 올해면 "10월 21일", 다른 해면 "2025년 10월 21일".
 * @param {string} iso
 * @param {Date} [now]
 * @returns {string}
 */
export function formatSearchTime(iso, now = new Date()) {
  const d = parseTime(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (sameDay(d, now)) return formatTime(iso);
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}월 ${d.getDate()}일`;
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/**
 * 결과 병합: id 로 중복을 없애고 최신(id 큰 것)이 먼저 오게 정렬한다.
 * @param {{ id: number }[]} existing
 * @param {{ id: number }[]} incoming
 * @returns {{ id: number }[]}
 */
export function mergeSearchResults(existing, incoming) {
  const byId = new Map();
  for (const item of [...(existing ?? []), ...(incoming ?? [])]) byId.set(Number(item.id), item);
  return [...byId.values()].sort((a, b) => Number(b.id) - Number(a.id));
}

/**
 * 결과 개수 문구. 서버가 전체 개수를 주지 않으므로 더 있으면 "N개 이상".
 * @param {number} count 지금까지 받은 개수
 * @param {boolean} hasMore
 * @returns {string}
 */
export const resultCountLabel = (count, hasMore) => `${count}개${hasMore ? " 이상" : ""}`;

/**
 * 소통 탭 결과에 붙일 방 이름. 목록에 있는 방이면 그 이름(가족 전체방은 가족 이름, 1:1 은 상대 표시 이름), 없으면 종류와 구성원으로, 모르면 "대화".
 * @param {{ room_id: string, room_kind?: string, peer_user_id?: string | null }} item
 * @param {{ id: string, name: string }[]} rooms 소통 탭 방 행
 * @param {{ id: string, name: string }[]} members 구성원(표시 이름)
 * @returns {string}
 */
export function searchRoomLabel(item, rooms, members) {
  const room = (Array.isArray(rooms) ? rooms : []).find((r) => r.id === item?.room_id);
  if (room?.name) return room.name;
  if (item?.room_kind === "direct") {
    const peer = (Array.isArray(members) ? members : []).find((m) => m.id === item.peer_user_id);
    return peer?.name || "대화";
  }
  return item?.room_kind === "family" ? "가족 채팅" : "대화";
}

/**
 * 결과를 눌렀을 때 갈 채팅방 경로. 가족 전체방은 roomId·peer 없이, 1:1 은 roomId·peer 를 넘기고, 둘 다 focus 로 메시지 id 를 넘긴다.
 * @param {{ id: number, room_id: string, room_kind?: string, peer_user_id?: string | null }} item
 * @returns {{ pathname: string, params: Record<string, string> }}
 */
export function focusRoute(item) {
  const params = { focus: String(item.id) };
  if (item.room_kind === "direct") {
    params.roomId = item.room_id;
    params.peer = item.peer_user_id ?? "";
  }
  return { pathname: "/chat-room", params };
}

/**
 * 경로 인자 focus 를 메시지 id 로. 양의 정수만 받는다.
 * @param {unknown} value
 * @returns {number | null}
 */
export function parseFocusParam(value) {
  const text = Array.isArray(value) ? value[0] : value;
  if (typeof text !== "string" || !/^\d{1,15}$/.test(text)) return null;
  const n = Number(text);
  return n >= 1 ? n : null;
}

const isTemp = (m) => m?.status === "sending" || m?.status === "failed";

/**
 * 임시(전송 중·실패) 메시지만 남긴다.
 * @param {object[]} messages
 * @returns {object[]}
 */
export const keepTemps = (messages) => (Array.isArray(messages) ? messages : []).filter(isTemp);

/**
 * 과거 창으로 목록을 바꾼다: 서버 메시지는 모두 창으로 교체하고(떨어진 구간이 이어 붙지 않게), 임시 메시지는 유지한다. 창 안은 id 중복 없이 오름차순.
 * @param {object[]} existing 지금 목록
 * @param {object[]} windowRows 서버가 돌려준 창(around_id)
 * @returns {object[]}
 */
export function replaceWindow(existing, windowRows) {
  const byId = new Map();
  for (const m of windowRows ?? []) byId.set(Number(m.id), m);
  const server = [...byId.values()].sort((a, b) => Number(a.id) - Number(b.id));
  return [...server, ...keepTemps(existing)];
}

/**
 * 아래로 더 불러온 결과가 라이브 끝에 닿았는지(요청한 개수보다 적게 왔으면 더 뒤가 없다).
 * @param {number} receivedCount
 * @param {number} [limit]
 * @returns {boolean}
 */
export const reachedLiveEnd = (receivedCount, limit = FOCUS_PAGE) => Number(receivedCount) < Number(limit);

/**
 * 과거 창에서 아래 끝 근처에 와서 이후 대화를 더 불러와야 하는지.
 * @param {{ focusing: boolean, fromBottom: number, near: number, busy: boolean }} state
 * @returns {boolean}
 */
export const shouldLoadNewer = ({ focusing, fromBottom, near, busy }) => Boolean(focusing) && !busy && fromBottom < near;

/**
 * 방 목록에서 가족 전체방의 id. 가족방 안 검색은 이 id 를 room_id 로 넘겨 1:1 방이 섞이지 않게 한다. 없으면 null.
 * @param {{ id: string, kind: string }[] | null | undefined} rooms
 * @returns {string | null}
 */
export const familyRoomId = (rooms) => (Array.isArray(rooms) ? rooms.find((r) => r?.kind === "family")?.id ?? null : null);

/**
 * 방 안 검색의 범위 방 id. 1:1 방은 그 방 id, 가족 전체방은 방 목록에서 알아낸 가족방 id(아직 모르면 null → 검색을 막는다. 모든 방 검색으로 떨어지지 않게).
 * @param {string | null} roomId 경로 인자 roomId(가족 전체방이면 null)
 * @param {string | null} familyId 방 목록에서 알아낸 가족방 id
 * @returns {string | null}
 */
export const searchScopeRoomId = (roomId, familyId) => roomId || familyId || null;

/**
 * 채팅방 안 검색 훅에 넘길 옵션. 한 방 안 검색(scoped)이라 방 id 를 알기 전(null)에는 검색을 막는다.
 * @param {string | null} roomId 경로 인자 roomId(가족 전체방이면 null)
 * @param {string | null} familyId 방 목록에서 알아낸 가족방 id
 * @returns {{ roomId: string | null, scoped: true }}
 */
export const roomSearchOptions = (roomId, familyId) => ({ roomId: searchScopeRoomId(roomId, familyId), scoped: true });

/**
 * 검색 위치 이동 계산. 결과는 최신순이라 index 0 이 가장 최근 일치다. "older" 는 더 오래된 일치(index+1), "newer" 는 더 최근 일치(index-1).
 * 끝에서 older 인데 서버에 더 있으면 다음 쪽을 불러와야 한다(more), 끝이면 그대로 둔다.
 * @param {{ index: number, count: number, hasMore: boolean, dir: "older" | "newer" }} args
 * @returns {{ index: number, more: boolean }}
 */
export function stepSearchIndex({ index, count, hasMore, dir }) {
  if (count <= 0) return { index: 0, more: false };
  if (dir === "newer") return { index: Math.max(0, index - 1), more: false };
  if (index + 1 < count) return { index: index + 1, more: false };
  return { index, more: Boolean(hasMore) };
}

/**
 * 검색 줄의 위치 문구. 결과가 없으면 빈 문자열, 서버에 더 있으면 "1/20+".
 * @param {number} index 0부터 시작하는 현재 위치
 * @param {number} count 지금까지 받은 개수
 * @param {boolean} hasMore
 * @returns {string}
 */
export const searchPositionLabel = (index, count, hasMore) => (count > 0 ? `${Math.min(index, count - 1) + 1}/${count}${hasMore ? "+" : ""}` : "");
