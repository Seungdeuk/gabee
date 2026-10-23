/**
 * 서버(FastAPI) 호출 공통 래퍼. 화면에서 직접 fetch 하지 않고 각 기능의 api.js 가 이걸 쓴다.
 *
 * 서버 주소는 EXPO_PUBLIC_API_URL 로 정한다(apps/mobile/.env). 폰에서 개발 PC 서버에 붙을 때는
 * localhost 가 아니라 PC 의 IP 를 쓴다. 예: EXPO_PUBLIC_API_URL=http://192.168.0.10:8000
 * 주소가 없으면 isApiConfigured() 가 false 라서 각 기능은 임시(mock) 데이터로 동작한다.
 *
 * 인증은 두 가지이고 한 요청에 섞어 보내지 않는다.
 * - 정식 회원(로그인): `Authorization: Bearer <Access Token>`. 만료되면 Refresh Token 으로 자동 갱신하고 실패한 요청을 한 번만 다시 보낸다.
 * - 익명 계정(기존 방식, 개발용 토큰 포함): `X-Gyeot-Token`. 로그인 세션이 있으면 이 헤더는 절대 보내지 않는다.
 * 토큰 원문은 로그에 남기지 않는다.
 */
const BASE_URL = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/+$/, "");

// 익명 계정 토큰(기존 방식). 개발용 EXPO_PUBLIC_DEV_TOKEN 으로 시작하고, 익명 가입이 setToken 을 부르면 그 값으로 바뀐다.
let legacyToken = process.env.EXPO_PUBLIC_DEV_TOKEN ?? "";
// 로그인 세션: Access Token 은 메모리에만, Refresh Token 은 보안 저장소(앱이 hooks.onRefreshTokenChanged 로 저장)에 둔다.
let accessToken = "";
let refreshToken = "";
let refreshInFlight = null; // 동시에 여러 요청이 만료돼도 갱신은 한 번만 한다(Refresh Token 은 한 번 쓰면 폐기된다)
let hooks = {};

export const isApiConfigured = () => BASE_URL !== "";

/**
 * 앱이 연결하는 콜백.
 * @param {{ onRefreshTokenChanged?: (token: string) => void, onSessionLost?: (code: string) => void, onEmailNotVerified?: () => void }} next
 */
export function configureAuth(next) {
  hooks = { ...hooks, ...next };
}

/** 익명 계정 토큰(기존 방식)을 기억한다. 로그인 세션이 있으면 쓰이지 않는다. */
export function setToken(next) {
  legacyToken = next ?? "";
}

/**
 * 로그인(또는 복원) 뒤 세션을 기억한다. 이후 요청은 Bearer 로 나간다.
 * @param {{ accessToken?: string, refreshToken: string }} session
 */
export function setSession({ accessToken: access = "", refreshToken: refresh }) {
  accessToken = access;
  refreshToken = refresh;
}

/** 로컬 세션을 지운다(서버 로그아웃은 호출한 쪽이 한다). */
export function clearSession() {
  accessToken = "";
  refreshToken = "";
}

export const hasSession = () => refreshToken !== "" || accessToken !== "";
export const getRefreshToken = () => refreshToken;

/** 서버가 {code, message} 로 돌려준 오류. retryAfter 는 429 의 Retry-After(초). */
export class ApiError extends Error {
  constructor(status, code, message, retryAfter = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

async function rawFetch(path, { method, body, headers }) {
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: { ...(body && !isForm ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "서버에 연결하지 못했어요");
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  return { res, data };
}

function toError(res, data) {
  return new ApiError(
    res.status,
    data?.code ?? "error",
    data?.message ?? "요청을 처리하지 못했어요",
    Number(res.headers?.get?.("Retry-After") ?? 0) || 0,
  );
}

async function doRefresh() {
  if (!refreshToken) {
    throw new ApiError(401, "session_expired", "로그인이 만료됐어요. 다시 로그인해 주세요");
  }
  const { res, data } = await rawFetch("/family-group/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
  if (res.ok) {
    accessToken = data.access_token;
    refreshToken = data.refresh_token; // 회전: 이전 Refresh Token 은 이미 폐기됐다
    hooks.onRefreshTokenChanged?.(refreshToken);
    return;
  }
  if (res.status === 401 || res.status === 400) {
    // 만료·폐기·재사용(탈취 의심): 안전하게 로그아웃한다
    const code = data?.code ?? "refresh_invalid";
    clearSession();
    hooks.onSessionLost?.(code);
    throw new ApiError(401, "session_expired", "로그인이 만료됐어요. 다시 로그인해 주세요");
  }
  throw toError(res, data); // 서버 일시 오류(5xx·429): 세션은 그대로 둔다
}

/**
 * Access Token 을 Refresh Token 으로 갱신한다. 동시에 불러도 서버 호출은 한 번이다.
 * @returns {Promise<void>}
 */
export function refreshSession() {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/**
 * @param {string} path 예: "/care/summary/today"
 * @param {{ method?: string, body?: object | FormData, headers?: Record<string, string>, auth?: boolean }} [options]
 *   auth: false 면 인증 헤더 없이 보낸다(가입·로그인·메일 링크 확인 같은 공개 API).
 * @returns {Promise<any>} 응답 JSON (본문이 없으면 null)
 */
export async function apiFetch(path, { method = "GET", body, headers = {}, auth = true } = {}) {
  if (!isApiConfigured()) {
    throw new ApiError(0, "api_not_configured", "서버 주소(EXPO_PUBLIC_API_URL)가 설정되지 않았어요");
  }
  const send = async () => {
    let used = "";
    let authHeader = {};
    if (auth) {
      if (refreshToken && !accessToken) await refreshSession(); // 앱을 다시 켠 직후: Access Token 이 아직 없다
      if (accessToken) {
        used = accessToken;
        authHeader = { Authorization: `Bearer ${accessToken}` };
      } else if (legacyToken) {
        authHeader = { "X-Gyeot-Token": legacyToken };
      }
    }
    const { res, data } = await rawFetch(path, { method, body, headers: { ...authHeader, ...headers } });
    return { res, data, used };
  };

  let { res, data, used } = await send();
  const expired = res.status === 401 && ["token_expired", "token_invalid"].includes(data?.code);
  if (!res.ok && used && expired) {
    // 이미 다른 요청이 갱신했다면(토큰이 바뀌었다면) 다시 갱신하지 않고 새 토큰으로 한 번만 재시도한다
    if (accessToken === used) await refreshSession();
    ({ res, data } = await send());
  }
  if (!res.ok) {
    if (res.status === 403 && data?.code === "email_not_verified") hooks.onEmailNotVerified?.();
    throw toError(res, data);
  }
  return data;
}
