import { apiFetch } from "@/shared/api/client";

import { normalizeEmail, normalizeLoginId } from "./validation";

// 가입·로그인·메일 링크 확인은 로그인 전에 부르므로 인증 헤더를 붙이지 않는다(auth: false).

/**
 * 아이디/비밀번호/이메일로 회원가입한다(로그인은 하지 않는다).
 * @param {{ loginId: string, password: string, email: string, name: string, role?: "parent" | "child" | "other" }} form
 * @returns {Promise<{ user: object }>}
 */
export const signupAccount = ({ loginId, password, email, name, role = "child" }) =>
  apiFetch("/family-group/auth/signup", {
    method: "POST",
    auth: false,
    body: { login_id: normalizeLoginId(loginId), password, email: normalizeEmail(email), name: name.trim(), role },
  });

/**
 * 아이디 중복 확인.
 * @param {string} loginId
 * @returns {Promise<{ login_id: string, available: boolean }>}
 */
export const checkLoginIdAvailable = (loginId) =>
  apiFetch(`/family-group/auth/login-id-available?login_id=${encodeURIComponent(normalizeLoginId(loginId))}`, {
    auth: false,
  });

/** 인증 메일을 (다시) 보낸다. 로그인 상태에서만. */
export const requestEmailVerification = () => apiFetch("/family-group/auth/email/verify/request", { method: "POST" });

/** 메일의 토큰으로 이메일 인증을 완료한다(로그인 없이도 가능). */
export const confirmEmailVerification = (token) =>
  apiFetch("/family-group/auth/email/verify/confirm", { method: "POST", auth: false, body: { token } });

/** 비밀번호 재설정 메일을 요청한다. 가입된 주소인지와 상관없이 같은 응답이다. */
export const requestPasswordReset = (email) =>
  apiFetch("/family-group/auth/password/reset/request", {
    method: "POST",
    auth: false,
    body: { email: normalizeEmail(email) },
  });

/** 메일의 토큰과 새 비밀번호로 재설정한다. 모든 기기가 로그아웃된다. */
export const confirmPasswordReset = (token, newPassword) =>
  apiFetch("/family-group/auth/password/reset/confirm", {
    method: "POST",
    auth: false,
    body: { token, new_password: newPassword },
  });
