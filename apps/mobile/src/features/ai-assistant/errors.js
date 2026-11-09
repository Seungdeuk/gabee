// AI 채팅 탭의 오류 안내와 서버로 보낼 대화 이력 정리(순수 함수, 시험: tests/assistanterrors.test.js)

export const AI_OFF_TITLE = "AI 도우미가 꺼져 있어요";
export const AI_OFF_BODY =
  "AI에게 질문하면 관련된 가족 기록 일부가 외부 AI(Anthropic)로 전송돼 답을 만들어요. 전송은 질문할 때만 일어나고, 처방전·신분증·통장 같은 민감한 기록도 개인정보를 가린 글이 전송될 수 있어요. 가족 소유자나 관리자가 켤 수 있어요.";
export const AI_OFF_ASK_MANAGER = "소유자나 관리자에게 켜 달라고 요청해 주세요.";
export const AI_ON_DONE = "AI를 켰어요. 방금 질문을 다시 보내 주세요.";

const FALLBACK = "답변을 가져오지 못했어요. 잠시 후 다시 시도해 주세요.";

/**
 * 서버 오류 코드를 채팅 말풍선에 넣을 안내 문장으로 바꾼다. 대화 내용은 넣지 않는다.
 * @param {{ code?: string, message?: string } | null | undefined} error ApiError 등
 * @returns {string}
 */
export function assistantErrorText(error) {
  switch (error?.code) {
    case "ai_not_enabled":
      return AI_OFF_TITLE;
    case "ai_cooldown":
    case "ai_busy":
      return "조금 뒤에 다시 물어봐 주세요.";
    case "ai_daily_limit_user":
    case "ai_daily_limit_group":
      return "오늘 AI 사용 한도에 도달했어요. 내일 다시 물어봐 주세요.";
    case "llm_failed":
      return "AI 연결에 문제가 있어요. 잠시 뒤에 다시 시도해 주세요.";
    case "not_member":
      return "가족 그룹에 참여해야 쓸 수 있어요. 더보기(⋮)의 가족 그룹에서 참여해 주세요.";
    default:
      return error?.message || FALLBACK;
  }
}

/**
 * 오류 말풍선 한 개를 만든다. 오류용 말풍선(isError)은 서버로 보내는 대화 이력에서 빠진다.
 * @param {string} id 새 메시지 id
 * @param {{ code?: string, message?: string } | null | undefined} error
 * @returns {{ id: string, role: "assistant", text: string, sources: [], isError: true, aiOff?: true }}
 */
export function errorMessage(id, error) {
  const message = { id, role: "assistant", text: assistantErrorText(error), sources: [], isError: true };
  return error?.code === "ai_not_enabled" ? { ...message, aiOff: true } : message;
}

/**
 * 서버(→외부 AI)로 보낼 앞 대화. 오류 말풍선과, 그 오류를 부른 사용자 질문(답을 못 받은 질문)은 뺀다.
 * @param {{ role: "user" | "assistant", text: string, isError?: boolean }[]} messages
 * @returns {{ role: "user" | "assistant", text: string }[]}
 */
export function historyForServer(messages) {
  const out = [];
  messages.forEach((m, i) => {
    if (m.isError) return;
    if (m.role === "user" && messages[i + 1]?.isError) return;
    out.push({ role: m.role, text: m.text });
  });
  return out;
}
