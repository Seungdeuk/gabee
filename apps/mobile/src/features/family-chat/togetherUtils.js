// 채팅의 할 일 후보 → 함께하기(일정 탭의 같이 요청) 변환과, 서랍 "가족 할 일" 화면이 보여 주는 일정 탭 내역(할 일 + 함께하기)의 순수 함수.
// 화면·네트워크와 분리해 시험한다. 제목·메모는 어디에도 기록하지 않는다. 일정 기능의 파일은 가져오지 않고 서버 계약(openapi)만 따른다.

/** 함께하기 제목 최대 길이(서버 RequestCreate 와 같다). */
export const TITLE_MAX = 120;
/** 서랍 화면에 보이는 항목 최대 개수. */
export const BRIEF_LIMIT = 30;
/** 서버 일정 종류: 1 약속, 2 할 일. */
const KIND_TODO = 2;

/** 날짜를 고르는 칩: days 는 오늘부터 며칠 뒤인지. */
export const DAY_CHIPS = [
  { key: "today", label: "오늘", days: 0 },
  { key: "tomorrow", label: "내일", days: 1 },
  { key: "d3", label: "3일 뒤", days: 3 },
  { key: "w1", label: "1주일 뒤", days: 7 },
];

const pad = (n) => String(n).padStart(2, "0");

/**
 * 기기 시간대의 날짜를 YYYY-MM-DD 로.
 * @param {Date} d
 * @returns {string}
 */
export const dateKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/**
 * 칩이 뜻하는 날짜(기기 시간대의 오늘에서 days 일 뒤).
 * @param {string} key DAY_CHIPS 의 key
 * @param {Date} [now]
 * @returns {string | null} YYYY-MM-DD, 모르는 칩이면 null
 */
export function dayFromChip(key, now = new Date()) {
  const chip = DAY_CHIPS.find((c) => c.key === key);
  if (!chip) return null;
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + chip.days);
  return dateKey(d);
}

/**
 * 실제 있는 날짜인지(YYYY-MM-DD).
 * @param {unknown} value
 * @returns {boolean}
 */
export function isDay(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value ?? ""));
  if (!m) return false;
  const [y, mo, da] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const d = new Date(y, mo - 1, da);
  return d.getFullYear() === y && d.getMonth() === mo - 1 && d.getDate() === da;
}

/**
 * 제목을 한 줄로 정리하고 최대 길이로 자른다.
 * @param {unknown} title
 * @returns {string}
 */
export const cleanTitle = (title) => String(title ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, TITLE_MAX);

/**
 * 할 일 후보에 날짜가 이미 있는지(있으면 날짜를 고를 필요가 없다).
 * @param {{ due?: string | null } | null | undefined} candidate
 * @returns {boolean}
 */
export const hasCandidateDay = (candidate) => isDay(candidate?.due);

/**
 * 후보를 함께하기 요청 본문(POST /schedule/requests)으로. 사용자가 후보를 보고 누른 뒤에만 쓴다.
 * 날짜는 후보의 기한이 실제 날짜면 그것을, 아니면 사용자가 고른 날짜를 쓴다(둘 다 없으면 보낼 수 없다).
 * 받는 사람은 담당자 이름이 구성원 이름 또는 표시 이름과 정확히 같고 그런 사람이 한 명이며 내가 아닐 때 그 사람, 아니면 나를 뺀 가족 모두다.
 * @param {{ title?: string, assignee_name?: string | null, due?: string | null } | null | undefined} candidate
 * @param {{ my_id?: string | null, members?: { id: string, name?: string, display_name?: string | null }[] } | null | undefined} group 가족 정보(별명을 입히지 않은 원래 이름)
 * @param {string | null} [chosenDay] 사용자가 고른 날짜(YYYY-MM-DD)
 * @returns {{ body: { title: string, start_date: string, to_ids: string[] } } | { error: "no_title" | "no_date" | "no_recipient" }}
 */
export function candidateToRequestBody(candidate, group, chosenDay = null) {
  const title = cleanTitle(candidate?.title);
  if (!title) return { error: "no_title" };
  const startDate = hasCandidateDay(candidate) ? candidate.due : isDay(chosenDay) ? chosenDay : null;
  if (!startDate) return { error: "no_date" };
  const me = group?.my_id ?? null;
  const others = (Array.isArray(group?.members) ? group.members : []).filter((m) => m.id !== me);
  if (others.length === 0) return { error: "no_recipient" };
  const wanted = String(candidate?.assignee_name ?? "").trim();
  const hits = wanted ? (Array.isArray(group?.members) ? group.members : []).filter((m) => m.name === wanted || m.display_name === wanted) : [];
  const toIds = hits.length === 1 && hits[0].id !== me ? [hits[0].id] : others.map((m) => m.id);
  return { body: { title, start_date: startDate, to_ids: toIds } };
}

const ERROR_TEXT = {
  no_title: "제목이 비어 있어요",
  no_date: "날짜를 골라 주세요",
  no_recipient: "함께할 가족이 아직 없어요",
};

/**
 * 변환 실패 사유 문구.
 * @param {"no_title" | "no_date" | "no_recipient"} error
 * @returns {string}
 */
export const requestErrorText = (error) => ERROR_TEXT[error] ?? "보내지 못했어요. 다시 시도해 주세요";

/**
 * 함께하기를 보내는 API 오류 문구.
 * @param {{ status?: number } | null | undefined} error
 * @returns {string}
 */
export function sendErrorMessage(error) {
  if (error?.status === 0) return "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요";
  if (error?.status === 429) return "잠시 후 다시 시도해 주세요";
  if (error?.status === 400 || error?.status === 422) return "보내지 못했어요. 내용을 확인해 주세요";
  return "보내지 못했어요. 다시 시도해 주세요";
}

/**
 * 서랍 "가족 할 일" 화면의 항목들: 일정 탭의 **할 일**(안 끝낸 것, 날짜 지나지 않은 것)과 **함께하기**(내가 받은 것·보낸 것).
 * 날짜 빠른 순, 같으면 함께하기 먼저. 수락해서 생긴 내 할 일은 같은 함께하기 줄과 겹치므로 뺀다(origin_id 가 요청 id).
 * 거절(어려워요)한 요청·보낸 사람이 취소한 요청·날짜가 지난 요청은 뺀다.
 * @param {{ events?: object[], requests?: object[], myId: string | null, today: string, nameOf?: (userId: string) => string | undefined }} args
 * @returns {{ key: string, type: "todo" | "request", id: string, title: string, date: string, time: string | null, tag: string, route: { pathname: string, params: { id: string } } }[]}
 */
export function buildBrief({ events, requests, myId, today, nameOf }) {
  const reqs = (Array.isArray(requests) ? requests : []).filter((r) => r && !r.canceled && String(r.start_date ?? "") >= today);
  const reqIds = new Set(reqs.map((r) => r.id));
  const rows = [];
  for (const r of reqs) {
    const mine = r.from_id === myId;
    const recipients = Array.isArray(r.recipients) ? r.recipients : [];
    const me = recipients.find((x) => x.user_id === myId);
    let tag;
    if (mine) {
      const accepted = recipients.filter((x) => x.status === "accepted").length;
      tag = accepted > 0 ? `${accepted}명이 함께해요` : "답을 기다려요";
    } else if (me?.status === "declined") continue;
    else tag = me?.status === "accepted" ? "함께해요" : `${nameOf?.(r.from_id) || "가족"}님이 보냈어요`;
    rows.push({
      key: `r:${r.id}`,
      type: "request",
      id: r.id,
      title: String(r.title ?? ""),
      date: String(r.start_date),
      time: r.start_time ? String(r.start_time).slice(0, 5) : null,
      tag,
      route: { pathname: mine ? "/schedule/together-detail" : "/schedule/together-receive", params: { id: r.id } },
    });
  }
  for (const e of Array.isArray(events) ? events : []) {
    if (!e || e.kind !== KIND_TODO || e.checked || reqIds.has(e.origin_id)) continue;
    const date = String(e.start_date ?? "");
    if (!date || date < today) continue;
    rows.push({
      key: `e:${e.id}`,
      type: "todo",
      id: e.id,
      title: String(e.title ?? ""),
      date,
      time: e.start_time ? String(e.start_time).slice(0, 5) : null,
      tag: "내 할 일",
      route: { pathname: "/schedule/detail", params: { id: e.id } },
    });
  }
  const rank = (r) => (r.type === "request" ? 0 : 1);
  return rows.sort((a, b) => a.date.localeCompare(b.date) || rank(a) - rank(b) || String(a.time ?? "").localeCompare(String(b.time ?? ""))).slice(0, BRIEF_LIMIT);
}

/**
 * 항목의 날짜 줄: "10월 29일(수)" 에 시간이 있으면 " 오후 3:20" 대신 24시간 "15:20" 을 붙인다.
 * @param {{ date: string, time: string | null }} row
 * @returns {string}
 */
export function briefWhen(row) {
  const [y, m, d] = String(row?.date ?? "").split("-").map(Number);
  if (!y || !m || !d) return "";
  const day = new Date(y, m - 1, d);
  const week = ["일", "월", "화", "수", "목", "금", "토"][day.getDay()];
  return `${m}월 ${d}일(${week})${row.time ? ` ${row.time}` : ""}`;
}
