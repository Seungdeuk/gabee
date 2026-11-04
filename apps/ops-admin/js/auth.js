import { ApiError, request, setToken } from "./api.js";

/**
 * 로그인하고 토큰을 메모리에 둔다. 운영자인지는 운영 API 가 판단한다(403 operator_required).
 * @param {string} loginId 아이디
 * @param {string} password 비밀번호
 * @returns {Promise<void>}
 */
export async function login(loginId, password) {
  const data = await request("/family-group/auth/login", {
    method: "POST", body: { login_id: loginId, password },
  });
  if (!data.access_token) throw new ApiError(0, "invalid_response", "로그인 응답에 토큰이 없어요");
  setToken(data.access_token);
}

/** 토큰을 지운다. */
export function logout() {
  setToken(null);
}
