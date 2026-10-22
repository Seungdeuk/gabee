// API 클라이언트의 인증 동작을 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

let counter = 0;
const realFetch = globalThis.fetch;

/** 모듈 상태(토큰 변수)가 시험마다 새로 시작하도록 매번 새로 불러온다. */
const load = () => import(`../src/shared/api/client.js?case=${++counter}`);

const json = (status, body, headers = {}) =>
  new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

/** 서버 흉내: 유효한 Access Token 집합, 유효한 Refresh Token 집합(한 번 쓰면 폐기), 호출 기록. */
function fakeServer() {
  const server = {
    calls: [],
    validAccess: new Set(["access-1"]),
    validRefresh: new Set(["refresh-1"]),
    refreshDelay: 0,
    refreshFails: null, // { status, code }
    n: 1,
  };
  globalThis.fetch = async (url, init = {}) => {
    const path = new URL(url).pathname;
    const headers = init.headers ?? {};
    server.calls.push({ path, headers, body: init.body ? JSON.parse(init.body) : null });
    if (path === "/family-group/auth/refresh") {
      if (server.refreshDelay) await new Promise((r) => setTimeout(r, server.refreshDelay));
      if (server.refreshFails) return json(server.refreshFails.status, { code: server.refreshFails.code, message: "x" });
      const sent = JSON.parse(init.body).refresh_token;
      if (!server.validRefresh.delete(sent)) return json(401, { code: "refresh_reused", message: "x" });
      server.n += 1;
      server.validAccess.add(`access-${server.n}`);
      server.validRefresh.add(`refresh-${server.n}`);
      return json(200, { access_token: `access-${server.n}`, refresh_token: `refresh-${server.n}`, token_type: "bearer", expires_in: 900, refresh_expires_in: 1 });
    }
    const auth = headers.Authorization;
    if (auth) {
      const token = auth.replace("Bearer ", "");
      if (!server.validAccess.has(token)) return json(401, { code: "token_expired", message: "x" });
      return json(200, { ok: true, via: "bearer" });
    }
    if (headers["X-Gyeot-Token"] === "legacy-dev-token") return json(200, { ok: true, via: "legacy" });
    return json(401, { code: "token_required", message: "x" });
  };
  return server;
}

beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("세션이 없으면 기존 방식(X-Gyeot-Token)으로 나간다", async () => {
  const api = await load();
  const server = fakeServer();
  assert.deepEqual(await api.apiFetch("/care/records"), { ok: true, via: "legacy" });
  assert.equal(server.calls[0].headers["X-Gyeot-Token"], "legacy-dev-token");
  assert.equal(server.calls[0].headers.Authorization, undefined);
});

test("로그인 세션이 있으면 Bearer 만 보내고 레거시 토큰은 절대 섞지 않는다", async () => {
  const api = await load();
  const server = fakeServer();
  api.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  assert.equal((await api.apiFetch("/care/records")).via, "bearer");
  const { headers } = server.calls[0];
  assert.equal(headers.Authorization, "Bearer access-1");
  assert.equal(headers["X-Gyeot-Token"], undefined);
});

test("auth:false 는 어떤 인증 헤더도 보내지 않는다(가입·로그인)", async () => {
  const api = await load();
  const server = fakeServer();
  api.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  await api.apiFetch("/family-group/auth/signup", { method: "POST", body: { a: 1 }, auth: false }).catch(() => {});
  assert.equal(server.calls[0].headers.Authorization, undefined);
  assert.equal(server.calls[0].headers["X-Gyeot-Token"], undefined);
});

test("Access Token 만료 시 자동 갱신하고 실패한 요청을 한 번 다시 보낸다", async () => {
  const api = await load();
  const server = fakeServer();
  const saved = [];
  api.configureAuth({ onRefreshTokenChanged: (t) => saved.push(t) });
  api.setSession({ accessToken: "expired", refreshToken: "refresh-1" });
  assert.equal((await api.apiFetch("/care/records")).via, "bearer");
  const paths = server.calls.map((c) => c.path);
  assert.deepEqual(paths, ["/care/records", "/family-group/auth/refresh", "/care/records"]);
  assert.equal(server.calls[2].headers.Authorization, "Bearer access-2");
  assert.deepEqual(saved, ["refresh-2"]); // 회전된 Refresh Token 이 저장소에 전달된다
  assert.equal(api.getRefreshToken(), "refresh-2");
});

test("재시도도 실패하면 더 반복하지 않는다(무한 루프 방지)", async () => {
  const api = await load();
  const server = fakeServer();
  globalThis.fetch = async (url, init = {}) => {
    server.calls.push({ path: new URL(url).pathname });
    if (new URL(url).pathname.endsWith("/auth/refresh")) {
      return json(200, { access_token: "still-bad", refresh_token: "r2", token_type: "bearer", expires_in: 1, refresh_expires_in: 1 });
    }
    return json(401, { code: "token_expired", message: "x" });
  };
  api.setSession({ accessToken: "expired", refreshToken: "refresh-1" });
  await assert.rejects(api.apiFetch("/care/records"), { code: "token_expired" });
  assert.equal(server.calls.length, 3); // 요청, 갱신, 재시도 — 그 이상 없음
});

test("동시에 여러 요청이 만료돼도 갱신은 한 번만 한다", async () => {
  const api = await load();
  const server = fakeServer();
  server.refreshDelay = 30;
  api.setSession({ accessToken: "expired", refreshToken: "refresh-1" });
  const results = await Promise.all(Array.from({ length: 8 }, (_, i) => api.apiFetch(`/care/records?i=${i}`)));
  assert.ok(results.every((r) => r.via === "bearer"));
  const refreshes = server.calls.filter((c) => c.path === "/family-group/auth/refresh");
  assert.equal(refreshes.length, 1); // 2번 이상이면 서버가 이미 쓴 Refresh Token 재사용으로 세션을 끊는다
});

test("다른 요청이 이미 갱신했다면 새 토큰으로 바로 재시도한다", async () => {
  const api = await load();
  const server = fakeServer();
  api.setSession({ accessToken: "expired", refreshToken: "refresh-1" });
  const slow = api.apiFetch("/care/records?slow");
  await api.refreshSession(); // 다른 곳에서 갱신
  await slow;
  assert.equal(server.calls.filter((c) => c.path === "/family-group/auth/refresh").length, 1);
});

test("Refresh Token 이 만료·재사용이면 안전하게 로그아웃한다", async () => {
  for (const code of ["refresh_invalid", "refresh_reused"]) {
    const api = await load();
    const server = fakeServer();
    server.refreshFails = { status: 401, code };
    const lost = [];
    api.configureAuth({ onSessionLost: (c) => lost.push(c) });
    api.setSession({ accessToken: "expired", refreshToken: "refresh-1" });
    await assert.rejects(api.apiFetch("/care/records"), { code: "session_expired", status: 401 });
    assert.deepEqual(lost, [code]);
    assert.equal(api.hasSession(), false);
    assert.equal(api.getRefreshToken(), "");
  }
});

test("서버가 잠시 불안정하거나 네트워크가 끊겨도 세션은 지우지 않는다", async () => {
  const api = await load();
  const server = fakeServer();
  server.refreshFails = { status: 503, code: "auth_not_configured" };
  api.setSession({ accessToken: "expired", refreshToken: "refresh-1" });
  await assert.rejects(api.apiFetch("/care/records"), { status: 503 });
  assert.equal(api.hasSession(), true);

  globalThis.fetch = async () => {
    throw new TypeError("offline");
  };
  await assert.rejects(api.apiFetch("/care/records"), { code: "network_error" });
  assert.equal(api.hasSession(), true);
});

test("앱을 다시 켠 직후(Refresh Token 만 있음)에는 먼저 갱신해서 요청한다", async () => {
  const api = await load();
  const server = fakeServer();
  api.setSession({ refreshToken: "refresh-1" });
  assert.equal((await api.apiFetch("/family-group/auth/me")).via, "bearer");
  assert.equal(server.calls[0].path, "/family-group/auth/refresh");
});

test("403 email_not_verified 는 안내 화면으로 연결할 수 있게 알린다", async () => {
  const api = await load();
  globalThis.fetch = async () => json(403, { code: "email_not_verified", message: "x" });
  let notified = 0;
  api.configureAuth({ onEmailNotVerified: () => (notified += 1) });
  api.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  await assert.rejects(api.apiFetch("/family-group/groups", { method: "POST", body: { name: "x" } }), { code: "email_not_verified" });
  assert.equal(notified, 1);
});

test("로그아웃으로 세션을 지우면 다시 기존 방식으로 돌아간다", async () => {
  const api = await load();
  const server = fakeServer();
  api.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  api.clearSession();
  await api.apiFetch("/care/records");
  assert.equal(server.calls[0].headers["X-Gyeot-Token"], "legacy-dev-token");
});

test("서버 오류의 Retry-After 와 코드가 ApiError 에 담긴다", async () => {
  const api = await load();
  globalThis.fetch = async () => json(429, { code: "too_many_requests", message: "m" }, { "Retry-After": "42" });
  await assert.rejects(api.apiFetch("/x", { auth: false }), (e) => e.code === "too_many_requests" && e.retryAfter === 42);
});
