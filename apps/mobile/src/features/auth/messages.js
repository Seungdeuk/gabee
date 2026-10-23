/**
 * 서버 오류(ApiError)를 사용자에게 보여줄 문장으로 바꾼다. 모르는 코드는 서버가 준 message 를 그대로 쓴다.
 * 메시지에는 토큰이나 입력한 비밀번호를 넣지 않는다.
 */
const BY_CODE = {
  network_error: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요",
  api_not_configured: "서버 주소가 설정되지 않아 이 기능을 쓸 수 없어요",
  invalid_credentials: "아이디 또는 비밀번호가 올바르지 않아요",
  too_many_attempts: "로그인 시도가 너무 많아요. 잠시 후 다시 시도해 주세요",
  login_id_taken: "이미 사용 중인 아이디예요",
  email_taken: "이미 가입된 이메일이에요. 비밀번호를 잊으셨다면 재설정을 이용해 주세요",
  invalid_login_id: "사용할 수 없는 아이디예요",
  invalid_email: "이메일 형식이 올바르지 않아요",
  invalid_name: "이름을 확인해 주세요",
  weak_password: "비밀번호 규칙에 맞지 않아요",
  mail_not_configured: "지금은 인증 메일을 보낼 수 없어요. 서버의 메일 설정이 끝나면 다시 시도해 주세요",
  mail_send_failed: "메일을 보내지 못했어요. 잠시 후 다시 시도해 주세요",
  auth_not_configured: "로그인 기능이 아직 서버에 설정되지 않았어요",
  email_already_verified: "이미 인증된 이메일이에요",
  email_not_verified: "이메일 인증을 먼저 완료해 주세요",
  verification_invalid: "인증 링크(코드)가 올바르지 않아요",
  verification_used: "이미 사용된 인증 링크예요",
  verification_expired: "인증 링크가 만료됐어요. 인증 메일을 다시 받아 주세요",
  reset_token_invalid: "재설정 링크(코드)가 올바르지 않아요",
  reset_token_used: "이미 사용된 재설정 링크예요. 필요하면 다시 요청해 주세요",
  reset_token_expired: "재설정 링크가 만료됐어요. 다시 요청해 주세요",
  session_expired: "로그인이 만료됐어요. 다시 로그인해 주세요",
};

/** 초를 "45초" / "3분" 으로. */
export function formatWait(seconds) {
  return seconds < 60 ? `${seconds}초` : `${Math.ceil(seconds / 60)}분`;
}

/**
 * @param {{ code?: string, message?: string, retryAfter?: number } | null | undefined} error
 * @returns {string}
 */
export function errorMessage(error) {
  if (!error) return "";
  if (error.code === "too_many_requests") {
    const wait = error.retryAfter ? ` (${formatWait(error.retryAfter)} 뒤에 다시 시도할 수 있어요)` : "";
    return `요청이 너무 많아요. 잠시 후 다시 시도해 주세요${wait}`;
  }
  return BY_CODE[error.code] ?? error.message ?? "요청을 처리하지 못했어요";
}
