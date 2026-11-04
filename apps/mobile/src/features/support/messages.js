/** 고객센터(문의·신고) 문구와 입력 검사. 글자 수 한도는 서버 규칙과 같다(제목 1~100자, 내용 1~2000자). */

export const TITLE_MAX = 100;
export const BODY_MAX = 2000;

/** 보낼 때 고르는 종류(서버 kind). */
export const KIND_OPTIONS = [
  { key: "inquiry", label: "문의", icon: "help-circle-outline", desc: "사용 방법이나 궁금한 점" },
  { key: "report", label: "신고", icon: "flag-outline", desc: "오류나 부적절한 사용 제보" },
];

/** 문의하기 화면 맨 위 안내. */
export const WRITE_INTRO = {
  title: "무엇을 도와드릴까요?",
  sub: "남겨 주신 내용은 서비스 관리자가 확인하고, 답변은 \"내 문의\"에서 볼 수 있어요",
};

/** 내 문의 목록 위쪽 필터(건수는 화면에서 붙인다). */
export const FILTERS = [
  { key: "all", label: "전체" },
  { key: "waiting", label: "답변 대기" },
  { key: "answered", label: "답변 완료" },
];

/** 보낸 것이 없을 때와 필터에 맞는 것이 없을 때 안내. */
export const EMPTY_TEXT = {
  all: { title: "아직 보낸 문의가 없어요", sub: "궁금한 점이나 불편한 점을 남겨 주세요" },
  waiting: { title: "답변을 기다리는 문의가 없어요", sub: "" },
  answered: { title: "답변이 달린 문의가 아직 없어요", sub: "" },
};

/** 답변이 아직 없는 문의를 펼쳤을 때 안내. */
export const WAITING_NOTE = "답변이 달리면 알림으로 알려 드려요";

/** 신고에도 사용자가 직접 쓴 글만 전달된다는 안내. */
export const PRIVACY_NOTE = "직접 쓴 제목과 내용만 서비스 관리자에게 전달돼요. 가족 채팅 내용은 함께 전달되지 않아요.";

export const SENT_NOTICE = "보냈어요. 답변이 달리면 알림으로 알려 드릴게요";

/** 상태 표시. state 는 화면 색 구분, group 은 필터 묶음이다. */
const STATE = {
  answered: { label: "답변 완료", group: "answered" },
  closed: { label: "처리 완료", group: "answered" },
  working: { label: "처리 중", group: "waiting" },
  waiting: { label: "답변 대기", group: "waiting" },
};

const BY_CODE = {
  network_error: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요",
  api_not_configured: "서버 주소가 설정되지 않아 이 기능을 쓸 수 없어요",
  token_required: "로그인이 필요해요",
  token_invalid: "로그인이 필요해요",
  session_expired: "로그인이 만료됐어요. 다시 로그인해 주세요",
};

/**
 * 문의·신고 오류(ApiError)를 사용자에게 보여 줄 문장으로 바꾼다. 쓴 내용은 문장에 넣지 않는다.
 * @param {{ status?: number, code?: string, message?: string } | null | undefined} error
 * @returns {string}
 */
export function supportErrorMessage(error) {
  if (!error) return "";
  if (BY_CODE[error.code]) return BY_CODE[error.code];
  if (error.status === 401) return BY_CODE.token_required;
  if (error.status === 422) return "입력한 내용을 확인해 주세요. 제목은 100자, 내용은 2000자까지 쓸 수 있어요";
  if (error.status === 404) return "고객센터를 아직 쓸 수 없어요. 잠시 뒤에 다시 시도해 주세요";
  if (error.status === 429) return "너무 자주 보냈어요. 잠시 뒤에 다시 시도해 주세요";
  return "요청을 처리하지 못했어요. 잠시 뒤에 다시 시도해 주세요";
}

/**
 * 보내기 전 입력 검사: 종류를 고르고, 제목·내용의 앞뒤 공백을 지운 뒤 비어 있거나 한도를 넘으면 안 된다.
 * @param {{ kind: unknown, title: unknown, body: unknown }} input
 * @returns {{ ok: true, value: { kind: string, title: string, body: string } } | { ok: false, errors: { kind?: string, title?: string, body?: string } }}
 */
export function validateTicket({ kind, title, body }) {
  const errors = {};
  if (!KIND_OPTIONS.some((o) => o.key === kind)) errors.kind = "문의인지 신고인지 골라 주세요";
  const t = typeof title === "string" ? title.trim() : "";
  const b = typeof body === "string" ? body.trim() : "";
  if (!t) errors.title = "제목을 입력해 주세요";
  else if (t.length > TITLE_MAX) errors.title = `제목은 ${TITLE_MAX}자까지 쓸 수 있어요`;
  if (!b) errors.body = "내용을 입력해 주세요";
  else if (b.length > BODY_MAX) errors.body = `내용은 ${BODY_MAX}자까지 쓸 수 있어요`;
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return { ok: true, value: { kind, title: t, body: b } };
}

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/**
 * 시각을 한국 시간 "11월 4일" 로. 읽을 수 없으면 "".
 * @param {string | null | undefined} iso
 * @returns {string}
 */
export function dateText(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const kst = new Date(at.getTime() + KST_OFFSET_MS);
  return `${kst.getUTCMonth() + 1}월 ${kst.getUTCDate()}일`;
}

/**
 * 보낸 문의·신고 한 건을 화면용으로 정리한다(모르는 값이 와도 깨지지 않게).
 * 답변이 있으면 서버 상태와 상관없이 "답변 완료"로 보여 준다(관리자가 상태를 바꾸지 않고 답변만 남겨도 같게 보이도록).
 * @param {object} row TicketOut
 * @returns {{ id: string, kind: string, kindLabel: string, state: "answered" | "closed" | "working" | "waiting", statusLabel: string, group: "waiting" | "answered", title: string, body: string, answer: string, answered: boolean, sentOn: string, answeredOn: string }}
 */
export function ticketView(row) {
  const kind = KIND_OPTIONS.find((o) => o.key === row?.kind);
  const answer = typeof row?.answer === "string" ? row.answer.trim() : "";
  let state = "waiting";
  if (answer !== "") state = "answered";
  else if (row?.status === "done") state = "closed";
  else if (row?.status === "working") state = "working";
  return {
    id: String(row?.id ?? ""),
    kind: kind ? kind.key : "inquiry",
    kindLabel: kind ? kind.label : "문의",
    state,
    statusLabel: STATE[state].label,
    group: STATE[state].group,
    title: String(row?.title ?? ""),
    body: String(row?.body ?? ""),
    answer,
    answered: answer !== "",
    sentOn: dateText(row?.created_at),
    answeredOn: dateText(row?.answered_at),
  };
}

/**
 * 필터 칩에 붙일 건수.
 * @param {object[]} rows TicketOut 목록
 * @returns {{ all: number, waiting: number, answered: number }}
 */
export function ticketCounts(rows) {
  const counts = { all: 0, waiting: 0, answered: 0 };
  for (const row of Array.isArray(rows) ? rows : []) {
    counts.all += 1;
    counts[ticketView(row).group] += 1;
  }
  return counts;
}

/**
 * 필터에 맞는 문의만 순서를 지켜 고른다. 모르는 필터는 전체로 본다.
 * @param {object[]} rows TicketOut 목록
 * @param {string} filter "all" | "waiting" | "answered"
 * @returns {object[]}
 */
export function filterTickets(rows, filter) {
  const list = Array.isArray(rows) ? rows : [];
  if (filter !== "waiting" && filter !== "answered") return list;
  return list.filter((row) => ticketView(row).group === filter);
}
