// 실제 서버(격리된 임시 DB 로 띄운 FastAPI)에 대한 인증 흐름 시험. 평소 npm test 에서는 건너뛴다.
//
// 실행 방법은 docs/features/mobile-auth.md 참고. 서버는 임시 SQLite 로, MAIL_BACKEND=console(메일을 보내지 않고 로그에 출력),
// ACCESS_TOKEN_TTL_SECONDS=2 로 띄우고 GABEE_E2E_API_URL / GABEE_E2E_MAIL_LOG(서버 로그 파일)를 알려 준다.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { before, describe, test } from "node:test";

const URL_BASE = process.env.GABEE_E2E_API_URL;
const MAIL_LOG = process.env.GABEE_E2E_MAIL_LOG;
const skip = !URL_BASE || !MAIL_LOG ? "GABEE_E2E_API_URL / GABEE_E2E_MAIL_LOG 가 필요해요" : false;

process.env.EXPO_PUBLIC_API_URL = URL_BASE ?? "";
process.env.EXPO_PUBLIC_DEV_TOKEN = "";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const lastMailToken = (kind) => {
  const matches = [...readFileSync(MAIL_LOG, "utf-8").matchAll(new RegExp(`${kind}\\?token=([\\w-]+)`, "g"))];
  return matches.at(-1)?.[1];
};

describe("모바일 API 클라이언트 ↔ 실제 서버", { skip }, () => {
  let api;
  let auth;
  let sessionApi;
  const sent = []; // 보낸 요청의 인증 헤더 기록
  const suffix = Date.now().toString(36);
  const form = {
    loginId: `mobile_${suffix}`,
    password: "Sunny-day-2026",
    email: `mobile_${suffix}@example.com`,
    name: "모바일",
  };

  before(async () => {
    const realFetch = globalThis.fetch;
    globalThis.fetch = (url, init = {}) => {
      sent.push({ path: new URL(url).pathname, headers: { ...(init.headers ?? {}) } });
      return realFetch(url, init);
    };
    api = await import("../src/shared/api/client.js");
    auth = await import("../src/features/auth/api.js");
    sessionApi = await import("../src/shared/auth/sessionApi.js");
  });

  test("가입 → 중복 처리 → 로그인", async () => {
    assert.equal((await auth.checkLoginIdAvailable(form.loginId)).available, true);
    const res = await auth.signupAccount(form);
    assert.equal(res.user.email_verified, false);
    assert.equal((await auth.checkLoginIdAvailable(form.loginId)).available, false);
    await assert.rejects(auth.signupAccount(form), { code: "login_id_taken" });
    await assert.rejects(auth.signupAccount({ ...form, loginId: `other_${suffix}` }), { code: "email_taken" });
    await assert.rejects(sessionApi.login(form.loginId, "Wrong-pass-1"), { code: "invalid_credentials" });

    const login = await sessionApi.login(form.loginId, form.password, "e2e");
    api.setSession({ accessToken: login.access_token, refreshToken: login.refresh_token });
    assert.equal((await sessionApi.getMe()).login_id, form.loginId);
  });

  test("이메일 미인증이면 그룹 생성이 403, 인증 메일 → 인증 후에는 성공", async () => {
    let notified = 0;
    api.configureAuth({ onEmailNotVerified: () => (notified += 1) });
    await assert.rejects(api.apiFetch("/family-group/groups", { method: "POST", body: { name: "가족" } }), { code: "email_not_verified" });
    assert.equal(notified, 1);

    await auth.requestEmailVerification();
    const token = lastMailToken("verify-email");
    assert.ok(token, "개발용 메일 출력에서 인증 토큰을 찾지 못했어요");
    await assert.rejects(auth.confirmEmailVerification("x".repeat(30)), { code: "verification_invalid" });
    await auth.confirmEmailVerification(token); // 로그인 없이도 되는 API
    await assert.rejects(auth.confirmEmailVerification(token), { code: "verification_used" });
    assert.equal((await sessionApi.getMe()).email_verified, true);
    assert.equal((await api.apiFetch("/family-group/groups", { method: "POST", body: { name: "가족" } })).name, "가족");
  });

  test("Access Token 이 만료되면 자동 갱신되고, 동시 요청에서도 갱신은 한 번이다", async () => {
    await sleep(2500); // 서버 Access Token 수명 2초
    sent.length = 0;
    const results = await Promise.all(Array.from({ length: 6 }, () => api.apiFetch("/family-group/me")));
    assert.ok(results.every((r) => r.login_id === form.loginId));
    assert.equal(sent.filter((c) => c.path === "/family-group/auth/refresh").length, 1);
    assert.ok(sent.every((c) => c.headers["X-Gyeot-Token"] === undefined)); // 정식 회원 요청에 레거시 헤더가 없다
  });

  test("로그아웃하면 서버 세션이 끝나 Refresh Token 을 더 쓸 수 없다", async () => {
    const refreshToken = api.getRefreshToken();
    await sessionApi.logoutOnServer(refreshToken);
    await sessionApi.logoutOnServer(refreshToken); // 반복해도 안전
    api.setSession({ refreshToken }); // 폐기된 토큰으로 복원 시도
    const lost = [];
    api.configureAuth({ onSessionLost: (c) => lost.push(c) });
    await assert.rejects(api.apiFetch("/family-group/auth/me"), { code: "session_expired" });
    assert.equal(lost.length, 1);
    assert.equal(api.hasSession(), false);
  });

  test("비밀번호 재설정: 메일 코드로 변경, 모든 세션 종료, 새 비밀번호로 로그인", async () => {
    const old = await sessionApi.login(form.loginId, form.password);
    api.setSession({ accessToken: old.access_token, refreshToken: old.refresh_token });
    await auth.requestPasswordReset(form.email);
    await auth.requestPasswordReset("nobody@example.com"); // 없는 주소도 같은 성공 응답
    const token = lastMailToken("reset-password");
    assert.ok(token);
    await assert.rejects(auth.confirmPasswordReset(token, "short"), { code: "weak_password" });
    await auth.confirmPasswordReset(token, "Brand-new-pass-77");
    await assert.rejects(auth.confirmPasswordReset(token, "Brand-new-pass-88"), { code: "reset_token_used" });

    // 이전 세션은 즉시 끝난다(Access Token 도 거부, Refresh 도 거부 → 안전한 로그아웃)
    await assert.rejects(api.apiFetch("/family-group/auth/me"), { code: "session_expired" });
    await assert.rejects(sessionApi.login(form.loginId, form.password), { code: "invalid_credentials" });
    const fresh = await sessionApi.login(form.loginId, "Brand-new-pass-77");
    assert.ok(fresh.access_token);
  });

  test("기존 익명 계정 방식은 그대로 동작한다", async () => {
    api.clearSession();
    const res = await api.apiFetch("/family-group/users", { method: "POST", auth: false, body: { name: "익명", role: "child" } });
    api.setToken(res.token);
    sent.length = 0;
    const group = await api.apiFetch("/family-group/groups", { method: "POST", body: { name: "익명 가족" } });
    assert.equal(group.name, "익명 가족");
    assert.equal(sent[0].headers["X-Gyeot-Token"], res.token);
    assert.equal(sent[0].headers.Authorization, undefined);
    await api.apiFetch("/schedule/events"); // 기존 기능(일정)도 익명 계정으로 계속 쓸 수 있다
  });

  test("정식 회원의 레거시 토큰 우회 시도는 거부된다", async () => {
    const login = await sessionApi.login(form.loginId, "Brand-new-pass-77");
    api.setSession({ accessToken: login.access_token, refreshToken: login.refresh_token });
    // 남의 레거시 토큰을 Authorization 과 함께 보내도 Bearer 만 평가된다
    const bad = await fetch(`${URL_BASE}/family-group/me`, {
      headers: { Authorization: "Bearer garbage", "X-Gyeot-Token": "whatever" },
    });
    assert.equal(bad.status, 401);
  });
});
