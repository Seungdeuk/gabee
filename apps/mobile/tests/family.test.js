// 가족 초대·가입 승인: 오류 문구·만료 안내와 API 호출 경로를 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { expiryText, familyErrorMessage, roleLabel } from "../src/features/family-group/messages.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) =>
  new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("가족 오류 문구: 서버 코드를 사용자 문장으로, 초대 코드는 넣지 않는다", () => {
  assert.match(familyErrorMessage({ code: "invalid_invite" }), /새 코드/);
  assert.match(familyErrorMessage({ code: "already_member" }), /이미/);
  assert.match(familyErrorMessage({ code: "not_manager" }), /관리자만/);
  assert.match(familyErrorMessage({ code: "join_request_already_decided" }), /이미 처리/);
  assert.match(familyErrorMessage({ code: "too_many_attempts", retryAfter: 45 }), /45초/);
  assert.match(familyErrorMessage({ code: "too_many_attempts", retryAfter: 600 }), /10분/);
  assert.equal(familyErrorMessage({ code: "something_new", message: "서버 문구" }), "서버 문구");
  assert.equal(familyErrorMessage(null), "");
});

test("초대 코드 만료 안내", () => {
  assert.equal(expiryText(null), "");
  assert.equal(expiryText("not-a-date"), "");
  assert.equal(expiryText(new Date(Date.now() - 1000).toISOString()), "만료됐어요");
  assert.match(expiryText(new Date(Date.now() + 90 * 60 * 1000 + 5000).toISOString()), /^1시간 30분 뒤 만료$/);
  assert.match(expiryText(new Date(Date.now() + 10 * 60 * 1000 + 5000).toISOString()), /^10분 뒤 만료$/);
});

test("가족 안 권한 이름", () => {
  assert.equal(roleLabel("owner"), "소유자");
  assert.equal(roleLabel("admin"), "관리자");
  assert.equal(roleLabel("member"), "구성원");
  assert.equal(roleLabel(undefined), "구성원");
});

test("가족 API 호출: 경로·메서드·본문, 로그인 세션이 있으면 Bearer 만", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} });
    return json(200, { status: "pending" });
  };
  const client = await import("../src/shared/api/client.js");
  const api = await import("../src/features/family-group/api.js");
  client.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  await api.requestJoin("K7M2Q9XW4P");
  await api.getMyJoinRequest();
  await api.cancelJoinRequest("r1");
  await api.reissueInvite();
  await api.revokeInvite();
  await api.listJoinRequests();
  await api.approveJoinRequest("r2");
  await api.rejectJoinRequest("r3");
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.path}`),
    [
      "POST /family-group/groups/join",
      "GET /family-group/groups/join-requests/mine",
      "POST /family-group/groups/join-requests/r1/cancel",
      "POST /family-group/groups/invites/reissue",
      "POST /family-group/groups/invites/revoke",
      "GET /family-group/groups/me/join-requests",
      "POST /family-group/groups/join-requests/r2/approve",
      "POST /family-group/groups/join-requests/r3/reject",
    ],
  );
  assert.deepEqual(calls[0].body, { code: "K7M2Q9XW4P" }); // 권한(role) 같은 값은 보내지 않는다
  assert.ok(calls.every((c) => c.headers.Authorization === "Bearer access-1" && c.headers["X-Gyeot-Token"] === undefined));
  assert.ok(calls.slice(1).every((c) => c.body === null));
});

test("소셜 로그인 설정: 값이 있는 제공자만 켜지고, 후보 응답을 알아본다", async () => {
  const social = await import("../src/features/auth/social.js");
  const saved = { ...process.env };
  try {
    for (const k of Object.keys(process.env)) if (k.startsWith("EXPO_PUBLIC_GOOGLE") || k.startsWith("EXPO_PUBLIC_KAKAO")) delete process.env[k];
    assert.deepEqual(social.enabledProviders(), []); // 아무 설정이 없으면 버튼이 없다
    process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID = "web-id";
    assert.deepEqual(social.enabledProviders(), ["google"]);
    process.env.EXPO_PUBLIC_KAKAO_REST_API_KEY = "rest-key";
    assert.deepEqual(social.enabledProviders(), ["google", "kakao"]);
  } finally {
    for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k];
    Object.assign(process.env, saved);
  }
  assert.equal(social.isCandidate({ candidate_account: true, masked_email: "j***@example.com" }), true);
  assert.equal(social.isCandidate({ access_token: "a", candidate_account: true }), false);
  assert.equal(social.isCandidate(null), false);
});

test("소셜 API 호출 경로와 본문(토큰은 본문에만, 비밀번호는 있을 때만)", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} });
    return json(200, {});
  };
  const api = await import("../src/features/auth/api.js");
  const client = await import("../src/shared/api/client.js");
  client.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  await api.socialLogin("google", "id-token-value");
  await api.listSocialAccounts();
  await api.linkSocialAccount("kakao", "kakao-token", "Sunny-day-2026");
  await api.linkSocialAccount("google", "id-token-value");
  await api.unlinkSocialAccount("kakao");
  assert.deepEqual(calls.map((c) => `${c.method} ${c.path}`), [
    "POST /family-group/auth/social/google",
    "GET /family-group/auth/social",
    "POST /family-group/auth/social/kakao/link",
    "POST /family-group/auth/social/google/link",
    "DELETE /family-group/auth/social/kakao",
  ]);
  assert.deepEqual(calls[0].body, { provider_token: "id-token-value", role: "child" });
  assert.equal(calls[0].headers.Authorization, undefined); // 로그인 전 호출이라 인증 헤더가 없다
  assert.deepEqual(calls[2].body, { provider_token: "kakao-token", password: "Sunny-day-2026" });
  assert.deepEqual(calls[3].body, { provider_token: "id-token-value" });
  assert.equal(calls[2].headers.Authorization, "Bearer access-1");
});

test("가족 관계·이름 표시 규칙: 별명 > 표시 이름 > 계정 이름", async () => {
  const { relationText, shownName, RELATIONS } = await import("../src/features/family-group/relations.js");
  assert.deepEqual(RELATIONS.map((r) => r.label), ["엄마", "아빠", "아들", "딸", "할머니", "할아버지", "기타"]);
  assert.equal(relationText({ family_relation: "mom" }), "엄마");
  assert.equal(relationText({ family_relation: "other", family_relation_detail: "이모" }), "이모");
  assert.equal(relationText({ family_relation: "other" }), "기타");
  assert.equal(relationText({}), "");
  assert.equal(relationText(null), "");
  assert.equal(shownName({ name: "지민", display_name: "우리 지민" }, { nickname: "딸" }), "딸");
  assert.equal(shownName({ name: "지민", display_name: "우리 지민" }, undefined), "우리 지민");
  assert.equal(shownName({ name: "지민", display_name: null }, { nickname: null }), "지민");
});

test("프로필·별명·권한 API 호출 경로와 본문", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null });
    return json(200, {});
  };
  const api = await import("../src/features/family-group/api.js");
  await api.updateMyProfile({ display_name: "지민", family_relation: "other", family_relation_detail: "이모" });
  await api.setMemberRole("u1", "admin");
  await api.listNicknames();
  await api.setNickname("u2", { nickname: "삼촌", memo: "" });
  await api.setNickname("u2", { nickname: "", memo: "" });
  assert.deepEqual(calls.map((c) => `${c.method} ${c.path}`), [
    "PUT /family-group/groups/me/profile",
    "PUT /family-group/groups/members/u1/role",
    "GET /family-group/groups/me/nicknames",
    "PUT /family-group/groups/me/nicknames/u2",
    "PUT /family-group/groups/me/nicknames/u2",
  ]);
  assert.deepEqual(calls[1].body, { role: "admin" }); // owner 로 올리는 값은 보내지 않는다
  assert.deepEqual(calls[3].body, { nickname: "삼촌", memo: null }); // 빈 값은 null(지우기)
  assert.deepEqual(calls[4].body, { nickname: null, memo: null });
});

test("가족 나가기: POST /family-group/groups/me/leave, 204 는 null", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push(`${init.method ?? "GET"} ${new URL(url).pathname}`);
    return new Response(null, { status: 204 });
  };
  const api = await import("../src/features/family-group/api.js");
  assert.equal(await api.leaveFamily(), null);
  assert.deepEqual(calls, ["POST /family-group/groups/me/leave"]);
});

test("가족 오류 문구: 소유자는 나갈 수 없다", () => {
  assert.match(familyErrorMessage({ code: "cannot_leave_owner" }), /소유자는 가족을 나갈 수 없어요/);
  assert.match(familyErrorMessage({ code: "no_group" }), /가족 그룹/);
  assert.match(familyErrorMessage({ code: "not_member" }), /구성원이 아니에요/);
});
