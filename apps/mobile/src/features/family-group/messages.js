/**
 * 가족 초대·가입 승인 오류(ApiError)를 사용자에게 보여줄 한국어 문장으로 바꾼다. 초대 코드는 문장에 넣지 않는다.
 */
const BY_CODE = {
  network_error: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요",
  api_not_configured: "서버 주소가 설정되지 않아 이 기능을 쓸 수 없어요",
  invalid_invite: "초대 코드가 올바르지 않거나 더 이상 쓸 수 없어요. 코드가 만료됐을 수 있으니 가족 관리자에게 새 코드를 받아 주세요",
  already_member: "이미 이 가족 그룹의 구성원이에요",
  too_many_attempts: "초대 코드를 너무 많이 틀렸어요. 잠시 후 다시 시도해 주세요",
  not_manager: "가족 관리자만 할 수 있어요",
  not_member: "이 가족 그룹의 구성원이 아니에요",
  not_found: "요청을 찾을 수 없어요. 이미 처리됐거나 취소됐을 수 있어요",
  join_request_already_decided: "이미 처리된 가입 요청이에요. 목록을 새로 불러올게요",
  no_group: "가족 그룹에 먼저 참여해 주세요",
  email_not_verified: "이메일 인증을 먼저 완료해 주세요",
  token_required: "로그인이 필요해요",
  token_invalid: "로그인이 필요해요",
  session_expired: "로그인이 만료됐어요. 다시 로그인해 주세요",
};

/**
 * @param {{ code?: string, message?: string, retryAfter?: number } | null | undefined} error
 * @returns {string}
 */
export function familyErrorMessage(error) {
  if (!error) return "";
  if (error.code === "too_many_attempts" && error.retryAfter) {
    const wait = error.retryAfter < 60 ? `${error.retryAfter}초` : `${Math.ceil(error.retryAfter / 60)}분`;
    return `${BY_CODE.too_many_attempts} (${wait} 뒤에 다시 시도할 수 있어요)`;
  }
  return BY_CODE[error.code] ?? error.message ?? "요청을 처리하지 못했어요";
}

/** 만료 시각을 "내일 오후 3:20 까지" 같은 안내로. 없으면 "". @param {string | null | undefined} iso */
export function expiryText(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const left = at.getTime() - Date.now();
  if (left <= 0) return "만료됐어요";
  const hours = Math.floor(left / 3600000);
  const minutes = Math.floor((left % 3600000) / 60000);
  return hours > 0 ? `${hours}시간 ${minutes}분 뒤 만료` : `${Math.max(1, minutes)}분 뒤 만료`;
}

/** 가족 안의 권한을 사용자 문구로. @param {string | undefined} role */
export const roleLabel = (role) => (role === "owner" ? "소유자" : role === "admin" ? "관리자" : "구성원");
