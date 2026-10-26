/**
 * 메일의 6자리 인증번호 관련 상수와 순수 함수. 서버(app/features/family_group)와 같은 규칙이다.
 */
export const CODE_LENGTH = 6;
// 서버 EMAIL_VERIFY_TTL_SECONDS 기본값(3분)과 같다. 화면의 "남은 시간" 표시용이고, 실제 만료는 서버가 판단한다.
export const CODE_TTL_SECONDS = 3 * 60;

/**
 * 입력에서 숫자만 남기고 최대 6자리로 자른다(붙여 넣기·공백·하이픈 대비).
 * @param {string | null | undefined} input
 * @returns {string}
 */
export const digitsOnly = (input) => (input ?? "").replace(/\D/g, "").slice(0, CODE_LENGTH);

/**
 * 6자리가 모두 채워졌으면 그 코드를, 아니면 "".
 * @param {string | null | undefined} input
 * @returns {string}
 */
export function parseCode(input) {
  const digits = digitsOnly(input);
  return digits.length === CODE_LENGTH ? digits : "";
}

/**
 * 남은 초를 "02:48" 으로.
 * @param {number} seconds
 * @returns {string}
 */
export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
