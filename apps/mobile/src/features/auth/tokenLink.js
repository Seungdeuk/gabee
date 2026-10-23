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

/**
 * 웹에서 주소창과 브라우저 기록에 남은 `?token=` 을 지운다(주소만 바꾸고 새 기록 항목을 만들지 않는다).
 * 네이티브 앱에는 주소창이 없어서 아무 일도 하지 않는다. 라우트 파라미터는 화면이 router.setParams 로 따로 지운다.
 * @param {{ location?: { href: string }, history?: { state: unknown, replaceState: (state: unknown, title: string, url: string) => void } } | undefined} [win]
 * @returns {boolean} 주소를 고쳤으면 true
 */
export function scrubTokenFromBrowserUrl(win = globalThis.window) {
  if (!win?.history?.replaceState || !win.location?.href) return false;
  const url = new URL(win.location.href);
  if (!url.searchParams.has("token")) return false;
  url.searchParams.delete("token");
  win.history.replaceState(win.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  return true;
}
