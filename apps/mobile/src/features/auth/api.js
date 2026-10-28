import { apiFetch } from "@/shared/api/client";

import { normalizeEmail, normalizeLoginId } from "./validation";

// 가입·로그인·메일 링크 확인은 로그인 전에 부르므로 인증 헤더를 붙이지 않는다(auth: false).

/**
 * 아이디/비밀번호/이메일로 회원가입한다(로그인은 하지 않는다).
 * @param {{ loginId: string, password: string, email?: string, name: string, role?: "parent" | "child" | "other", roleDetail?: string }} form
 * @returns {Promise<{ user: object }>}
 */
export const signupAccount = ({ loginId, password, email, name, role = "child", roleDetail = "" }) =>
  apiFetch("/family-group/auth/signup", {
    method: "POST",
    auth: false,
    body: {
      login_id: normalizeLoginId(loginId),
      password,
      ...(email && email.trim() ? { email: normalizeEmail(email) } : {}), // 이메일은 선택
      name: name.trim(),
      role,
      ...(role === "other" && roleDetail.trim() ? { role_detail: roleDetail.trim() } : {}),
    },
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

/** 메일의 6자리 인증번호로 이메일 인증을 완료한다(로그인한 본인만). */
export const confirmEmailCode = (code) =>
  apiFetch("/family-group/auth/email/verify/confirm-code", { method: "POST", body: { code } });

/**
 * 비밀번호 재설정 코드를 메일로 요청한다. 아이디와 이메일이 같은 계정과 일치할 때만 메일이 가고, 응답은 항상 같다.
 * @param {string} loginId
 * @param {string} email
 * @returns {Promise<void>}
 */
export const requestPasswordReset = (loginId, email) =>
  apiFetch("/family-group/auth/password/reset/request", {
    method: "POST",
    auth: false,
    body: { login_id: normalizeLoginId(loginId), email: normalizeEmail(email) },
  });

/**
 * 가입한 이메일로 아이디를 보내 달라고 요청한다. 계정이 있는지와 상관없이 응답은 항상 같다(응답에 아이디는 없다).
 * @param {string} email
 * @returns {Promise<void>}
 */
export const recoverLoginId = (email) =>
  apiFetch("/family-group/auth/login-id/recover", { method: "POST", auth: false, body: { email: normalizeEmail(email) } });

/** 메일의 토큰과 새 비밀번호로 재설정한다. 모든 기기가 로그아웃된다. */
export const confirmPasswordReset = (token, newPassword) =>
  apiFetch("/family-group/auth/password/reset/confirm", {
    method: "POST",
    auth: false,
    body: { token, new_password: newPassword },
  });

/**
 * 메일의 6자리 코드와 아이디, 새 비밀번호로 재설정한다. 모든 기기가 로그아웃된다.
 * @param {string} loginId
 * @param {string} code 6자리 숫자
 * @param {string} newPassword
 * @returns {Promise<void>}
 */
export const confirmPasswordResetCode = (loginId, code, newPassword) =>
  apiFetch("/family-group/auth/password/reset/confirm-code", {
    method: "POST",
    auth: false,
    body: { login_id: normalizeLoginId(loginId), code, new_password: newPassword },
  });

/**
 * Google(ID 토큰)·카카오(액세스 토큰)로 로그인하거나 처음이면 가입한다. 같은 이메일의 기존 계정이 있으면 합치지 않고
 * { candidate_account: true, masked_email } 만 돌려준다.
 * @param {"google" | "kakao"} provider
 * @param {string} providerToken
 * @param {"parent" | "child" | "other"} [role] 처음 가입할 때만 쓴다
 */
export const socialLogin = (provider, providerToken, role = "child") =>
  apiFetch(`/family-group/auth/social/${provider}`, { method: "POST", auth: false, body: { provider_token: providerToken, role } });

/** 내 계정에 연결된 소셜 계정 목록. */
export const listSocialAccounts = () => apiFetch("/family-group/auth/social");

/**
 * 로그인한 내 계정에 소셜 계정을 연결한다. 비밀번호가 있는 계정은 비밀번호를 한 번 더 보낸다.
 * @param {"google" | "kakao"} provider
 * @param {string} providerToken
 * @param {string} [password]
 */
export const linkSocialAccount = (provider, providerToken, password) =>
  apiFetch(`/family-group/auth/social/${provider}/link`, {
    method: "POST",
    body: { provider_token: providerToken, ...(password ? { password } : {}) },
  });

/** 소셜 연동을 해제한다. 마지막 로그인 수단이면 서버가 거부한다. */
export const unlinkSocialAccount = (provider) => apiFetch(`/family-group/auth/social/${provider}`, { method: "DELETE" });

