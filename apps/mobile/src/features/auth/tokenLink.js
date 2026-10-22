/**
 * 메일의 링크(gabee://verify-email?token=...)나 코드로 받은 토큰을 꺼낸다.
 * 토큰은 로그·분석 도구에 남기면 안 되므로 이 모듈은 어떤 것도 출력하지 않는다.
 */

/**
 * 사용자가 붙여 넣은 값(링크 전체 또는 코드만)에서 토큰을 꺼낸다. 형식이 맞지 않으면 "".
 * @param {string | null | undefined} input
 * @returns {string}
 */
export function extractToken(input) {
  const text = (input ?? "").trim();
  if (!text) return "";
  const match = text.match(/[?&]token=([^&#\s]+)/);
  let token = match ? match[1] : text;
  try {
    token = decodeURIComponent(token);
  } catch {
    // 디코딩할 수 없으면 그대로 쓴다
  }
  return /^[A-Za-z0-9_-]{16,256}$/.test(token) ? token : "";
}
