import { apiFetch } from "@/shared/api/client";

/**
 * 로그인. 응답에 Access/Refresh Token 과 사용자 정보가 들어 있다.
 * @param {string} loginId
 * @param {string} password
 * @param {string} [deviceLabel] 서버 세션 목록에 남는 기기 이름
 * @returns {Promise<{ access_token: string, refresh_token: string, expires_in: number, user: object }>}
 */
export const login = (loginId, password, deviceLabel) =>
  apiFetch("/family-group/auth/login", {
    method: "POST",
    auth: false, // 로그인 전이라 인증 헤더를 붙이지 않는다
    body: { login_id: loginId.trim().toLowerCase(), password, device_label: deviceLabel || undefined },
  });

/** 서버에서 이 세션(Refresh Token)을 끝낸다. 이미 끝난 토큰이어도 서버는 204 로 답한다. */
export const logoutOnServer = (refreshToken) =>
  apiFetch("/family-group/auth/logout", { method: "POST", auth: false, body: { refresh_token: refreshToken } });

/** 로그인한 사용자 정보(Bearer 전용). */
export const getMe = () => apiFetch("/family-group/auth/me");
