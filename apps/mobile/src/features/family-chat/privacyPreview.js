/**
 * AI 에 보내기 전 확인(미리보기) 화면의 순수 함수. 서버 `POST /family-chat/ai/preview` 응답을 문구로 바꾼다.
 * 대화 글자·가명화된 텍스트는 여기서 로그에 남기지 않는다.
 */

import { chatErrorMessage } from "./messages";

/** 가려지는 정보 종류와 한국어 라벨. 배열 순서가 칩이 보이는 순서다. */
export const MASK_KINDS = [
  ["PHONE", "전화번호"],
  ["EMAIL", "이메일"],
  ["RRN", "주민번호"],
  ["CARD", "카드번호"],
  ["ACCOUNT", "계좌번호"],
  ["SECRET", "비밀번호·인증 정보"],
  ["ADDRESS", "주소"],
  ["PERSON", "이름"],
];

const UNKNOWN_LABEL = "기타 정보";

/** 0 보다 큰 정수만 센다. */
const countOf = (n) => (Number.isFinite(n) && n > 0 ? Math.floor(n) : 0);

/**
 * 가려지는 항목 요약 칩 문구. 개수가 0 인 종류는 뺀다. 순서는 MASK_KINDS, 모르는 종류는 맨 뒤 "기타 정보".
 * @param {Record<string, number> | null | undefined} masked 종류별 가린 개수
 * @returns {string[]} 예: ["전화번호 2개 가림", "이름 5개 가림"]
 */
export function maskedChips(masked) {
  if (!masked || typeof masked !== "object") return [];
  const known = new Set(MASK_KINDS.map(([kind]) => kind));
  const chips = MASK_KINDS.filter(([kind]) => countOf(masked[kind]) > 0).map(([kind, label]) => `${label} ${countOf(masked[kind])}개 가림`);
  const other = Object.keys(masked)
    .filter((kind) => !known.has(kind))
    .reduce((sum, kind) => sum + countOf(masked[kind]), 0);
  if (other > 0) chips.push(`${UNKNOWN_LABEL} ${other}개 가림`);
  return chips;
}

/**
 * 가려진 값의 총 개수.
 * @param {Record<string, number> | null | undefined} masked
 * @returns {number}
 */
export function maskedTotal(masked) {
  if (!masked || typeof masked !== "object") return 0;
  return Object.values(masked).reduce((sum, n) => sum + countOf(n), 0);
}

/**
 * 고위험 정보 때문에 제외되는 메시지 경고. 없으면 빈 문자열.
 * @param {number | null | undefined} blockedMessages
 * @returns {string}
 */
export function blockedWarning(blockedMessages) {
  const n = countOf(blockedMessages);
  return n > 0 ? `주민번호·카드·비밀번호처럼 민감한 정보가 있는 메시지 ${n}개는 보내지 않아요` : "";
}

/**
 * 서버 미리보기 응답을 화면용으로 다듬는다(없는 필드는 안전한 기본값).
 * @param {object | null | undefined} res
 * @returns {{ messageCount: number, masked: Record<string, number>, blockedMessages: number, lines: { id: number, speaker: string, text: string, blocked: boolean }[], aiEnabled: boolean, sendable: boolean }}
 */
export function parsePreview(res) {
  return {
    messageCount: countOf(res?.message_count),
    masked: res?.masked && typeof res.masked === "object" ? res.masked : {},
    blockedMessages: countOf(res?.blocked_messages),
    lines: Array.isArray(res?.lines) ? res.lines : [],
    aiEnabled: res?.ai_enabled !== false,
    sendable: res?.sendable !== false, // 구 서버 응답(필드 없음)은 보낼 수 있는 것으로 본다
  };
}

/**
 * "AI에 보내기" 를 막는 이유. 동의 꺼짐(`ai_enabled=false`)이 먼저이고, 그다음 보낼 수 있는 메시지 부족(`sendable=false`).
 * @param {{ aiEnabled: boolean, sendable?: boolean } | null | undefined} preview parsePreview 결과
 * @returns {"disabled" | "insufficient" | ""}
 */
export function sendBlockReason(preview) {
  if (!preview || preview.aiEnabled !== true) return "disabled";
  if (preview.sendable === false) return "insufficient";
  return "";
}

/** 보낼 수 있는 대화가 부족할 때의 경고 문구. */
export const INSUFFICIENT_WARNING = "민감정보가 있어 제외된 메시지가 많아서 지금은 AI에 보낼 수 있는 대화가 부족해요";

/**
 * "AI에 보내기" 를 누를 수 있는지.
 * @param {{ aiEnabled: boolean, sendable?: boolean } | null | undefined} preview parsePreview 결과
 * @returns {boolean}
 */
export function canSendToAi(preview) {
  return sendBlockReason(preview) === "";
}

/**
 * "보낼 내용 보기" 목록의 한 줄. 차단된 줄은 내용을 보이지 않고 '제외됨' 으로 둔다.
 * @param {{ speaker?: string, text?: string, blocked?: boolean }} line
 * @returns {string}
 */
export function previewLineText(line) {
  const speaker = line?.speaker ? `${line.speaker}: ` : "";
  return line?.blocked ? `${speaker}(제외됨)` : `${speaker}${line?.text ?? ""}`;
}

/**
 * 결과 아래 한 줄: 가린 개수·제외한 메시지 수. 둘 다 0 이거나 정보가 없으면 빈 문자열(생략).
 * @param {{ masked?: Record<string, number>, blocked_messages?: number } | null | undefined} privacy 응답 meta.privacy
 * @returns {string}
 */
export function privacyCaption(privacy) {
  if (!privacy) return "";
  const masked = maskedTotal(privacy.masked);
  const blocked = countOf(privacy.blocked_messages);
  if (masked > 0 && blocked > 0) return `개인정보 ${masked}개를 가려서 보냈고 메시지 ${blocked}개는 제외했어요`;
  if (masked > 0) return `개인정보 ${masked}개를 가려서 보냈어요`;
  if (blocked > 0) return `메시지 ${blocked}개는 제외하고 보냈어요`;
  return "";
}

/** 분석·답장·주제 추천 확인 단계의 이름. */
export const PREVIEW_ACTIONS = {
  analysis: "대화 분석",
  replies: "답장 추천",
  topics: "대화 주제 추천",
};

/**
 * 미리보기 실패 문구. 서버 코드(too_few_messages, no_group, 401 등)는 공통 문구를 쓰고 모르면 일반 문구.
 * @param {{ code?: string, message?: string } | null | undefined} error
 * @returns {string}
 */
export function previewErrorMessage(error) {
  return chatErrorMessage(error) || "보낼 내용을 확인하지 못했어요. 다시 시도해 주세요";
}
