/** 고객센터(문의·신고) 문구와 입력 검사. 글자 수 한도는 서버 규칙과 같다(제목 1~100자, 내용 1~2000자). */

export const TITLE_MAX = 100;
export const BODY_MAX = 2000;

/** 보낼 때 고르는 종류(서버 kind). */
export const KIND_OPTIONS = [
  { key: "inquiry", label: "문의" },
  { key: "report", label: "신고" },
];

/** 상태 표시(서버 status). 변경 이력은 없고 마지막 값만 온다. */
export const STATUS_LABEL = { new: "접수됨", working: "처리 중", done: "답변 완료" };

/** 신고에도 사용자가 직접 쓴 글만 전달된다는 안내. */
export const PRIVACY_NOTE = "직접 쓴 제목과 내용만 서비스 관리자에게 전달돼요. 가족 채팅 내용은 함께 전달되지 않아요.";

export const SENT_NOTICE = "보냈어요. 답변은 이 화면에서 확인할 수 있어요";

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
 * @param {object} row TicketOut
 * @returns {{ id: string, kindLabel: string, statusLabel: string, title: string, body: string, answer: string, answered: boolean, sentOn: string, answeredOn: string }}
 */
export function ticketView(row) {
  const kind = KIND_OPTIONS.find((o) => o.key === row?.kind);
  const answer = typeof row?.answer === "string" ? row.answer.trim() : "";
  return {
    id: String(row?.id ?? ""),
    kindLabel: kind ? kind.label : "문의",
    statusLabel: STATUS_LABEL[row?.status] ?? STATUS_LABEL.new,
    title: String(row?.title ?? ""),
    body: String(row?.body ?? ""),
    answer,
    answered: answer !== "",
    sentOn: dateText(row?.created_at),
    answeredOn: dateText(row?.answered_at),
  };
}
