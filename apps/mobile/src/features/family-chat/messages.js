/**
 * 가족 채팅(요약) 오류(ApiError)를 사용자에게 보여줄 한국어 문장으로 바꾼다. 대화 내용은 문장에 넣지 않는다.
 */
const BY_CODE = {
  network_error: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요",
  api_not_configured: "서버 주소가 설정되지 않아 이 기능을 쓸 수 없어요",
  too_few_messages: "요약할 대화가 아직 충분하지 않아요. 대화가 조금 더 쌓인 뒤에 눌러 주세요",
  llm_unavailable: "대화 요약 기능이 아직 서버에 설정되지 않았어요. 서버 관리자에게 AI 설정을 부탁해 주세요",
  llm_failed: "요약을 만들지 못했어요. 잠시 후 다시 시도해 주세요",
  no_group: "가족 그룹에 먼저 참여해 주세요",
  token_required: "로그인이 필요해요",
  token_invalid: "로그인이 필요해요",
  session_expired: "로그인이 만료됐어요. 다시 로그인해 주세요",
};

/**
 * @param {{ code?: string, message?: string, retryAfter?: number } | null | undefined} error
 * @returns {string}
 */
export function chatErrorMessage(error) {
  if (!error) return "";
  if (error.code === "too_many_requests") {
    const wait = error.retryAfter ? ` (${error.retryAfter < 60 ? `${error.retryAfter}초` : `${Math.ceil(error.retryAfter / 60)}분`} 뒤에 다시 시도할 수 있어요)` : "";
    return `요약을 너무 많이 요청했어요. 잠시 후 다시 시도해 주세요${wait}`;
  }
  return BY_CODE[error.code] ?? error.message ?? "요청을 처리하지 못했어요";
}

/** 요약 결과의 한 줄 설명. 예: "최근 대화 24개 기준 · 오후 3:20". @param {{ message_count: number, generated_at: string }} result */
export function summaryCaption(result) {
  const at = new Date(result.generated_at);
  const time = Number.isNaN(at.getTime()) ? "" : ` · ${at.getHours() < 12 ? "오전" : "오후"} ${at.getHours() % 12 || 12}:${String(at.getMinutes()).padStart(2, "0")}`;
  return `최근 대화 ${result.message_count}개 기준${time}`;
}
