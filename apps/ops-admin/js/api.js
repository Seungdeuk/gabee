import { config } from "./config.js";

let accessToken = null; // 메모리에만 둔다(새로고침하면 다시 로그인, 확정 14차)
let onUnauthorized = () => {};

/** @param {string|null} token Access Token */
export function setToken(token) {
  accessToken = token;
}

/** @param {() => void} fn 401 을 받았을 때 부를 함수 */
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

/** 서버 오류 응답({code, message})을 담는 오류. */
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/**
 * 서버를 부른다. 화면에서 직접 fetch 하지 않고 이 함수만 쓴다.
 * @param {string} path 예: "/family-group/auth/login"
 * @param {{method?: string, body?: object}} [opts]
 * @returns {Promise<any>} 응답 JSON
 */
export async function request(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (body) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let res;
  try {
    res = await fetch(config.apiBase + path, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "서버에 연결하지 못했어요");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new ApiError(res.status, data.code || "error", data.message || "요청에 실패했어요");
    // 로그인 요청 자체의 401 은 아이디·비밀번호 오류이므로 로그인 화면 재진입을 하지 않는다
    if (res.status === 401 && accessToken) onUnauthorized();
    throw err;
  }
  return data;
}
