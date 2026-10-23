/**
 * 서버(FastAPI) 호출 공통 래퍼. 화면에서 직접 fetch 하지 않고 각 기능의 api.js 가 이걸 쓴다.
 *
 * 서버 주소는 EXPO_PUBLIC_API_URL 로 정한다(apps/mobile/.env). 폰에서 개발 PC 서버에 붙을 때는
 * localhost 가 아니라 PC 의 IP 를 쓴다. 예: EXPO_PUBLIC_API_URL=http://192.168.0.10:8000
 * 주소가 없으면 isApiConfigured() 가 false 라서 각 기능은 임시(mock) 데이터로 동작한다.
 */
const BASE_URL = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/+$/, "");

// 로그인 화면이 붙기 전까지 개발용으로 쓰는 토큰(EXPO_PUBLIC_DEV_TOKEN). 가입·로그인이 setToken 을 부르면 그 값으로 바뀐다.
let token = process.env.EXPO_PUBLIC_DEV_TOKEN ?? "";

export const isApiConfigured = () => BASE_URL !== "";

/** 가입·로그인 뒤에 받은 토큰을 기억해서 이후 요청에 붙인다. */
export function setToken(next) {
  token = next ?? "";
}

/** 이미지 등을 서버에서 직접 받을 때 쓰는 주소와 로그인 헤더(토큰은 주소에 넣지 않는다). */
export const apiUrl = (path) => `${BASE_URL}${path}`;
export const authHeaders = () => (token ? { "X-Gyeot-Token": token } : {});

/** 서버가 {code, message} 로 돌려준 오류. */
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/**
 * @param {string} path 예: "/care/summary/today"
 * @param {{ method?: string, body?: object | FormData, headers?: Record<string, string> }} [options]
 * @returns {Promise<any>} 응답 JSON (본문이 없으면 null)
 */
export async function apiFetch(path, { method = "GET", body, headers = {} } = {}) {
  if (!isApiConfigured()) {
    throw new ApiError(0, "api_not_configured", "서버 주소(EXPO_PUBLIC_API_URL)가 설정되지 않았어요");
  }
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        ...(body && !isForm ? { "Content-Type": "application/json" } : {}),
        ...(token ? { "X-Gyeot-Token": token } : {}),
        ...headers,
      },
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "서버에 연결하지 못했어요");
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, data?.code ?? "error", data?.message ?? "요청을 처리하지 못했어요");
  }
  return data;
}
