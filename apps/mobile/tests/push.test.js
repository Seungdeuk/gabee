// 푸시: 토큰 형식·등록 조건·푸시 탭 이동·분류 켜기/끄기와 푸시 API 경로를 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  PREVIEW_OPTIONS,
  PUSH_CHANNEL_ID,
  createTokenTracker,
  isQuietOn,
  isUsableToken,
  routeForPush,
  shouldRegister,
  toggleKind,
  withQuiet,
} from "../src/features/notifications/push.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";
// 서버 주소는 불러올 때 읽으므로 환경 변수를 정한 뒤에 가져온다
const { getPushSettings, registerPushToken, savePushSettings, unregisterPushToken } = await import(
  "../src/features/notifications/api.js"
);

const realFetch = globalThis.fetch;
const calls = [];
beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    const noContent = String(url).endsWith("push-token"); // 토큰 등록·해제는 204(본문 없음)
    return new Response(noContent ? null : JSON.stringify({ enabled: true }), {
      status: noContent ? 204 : 200,
      headers: { "Content-Type": "application/json" },
    });
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("isUsableToken accepts Expo token shapes only", () => {
  assert.equal(isUsableToken("ExponentPushToken[abc]"), true);
  assert.equal(isUsableToken("ExpoPushToken[abc]"), true);
  for (const bad of ["abc", "", "ExponentPushToken[abc", "Exponent[abc]", null, undefined, 7]) {
    assert.equal(isUsableToken(bad), false, String(bad));
  }
  assert.equal(isUsableToken(`ExponentPushToken[${"x".repeat(300)}]`), false);
});

test("routeForPush always opens the notification box in stage 1", () => {
  assert.equal(routeForPush(undefined), "/notifications");
  assert.equal(routeForPush(null), "/notifications");
  assert.equal(routeForPush({ kind: "schedule", notification_id: "n1" }), "/notifications");
});

test("push channel id matches the server's channelId", () => {
  assert.equal(PUSH_CHANNEL_ID, "default");
});

test("shouldRegister only when authenticated on a native platform", () => {
  assert.equal(shouldRegister({ status: "authenticated", platform: "android" }), true);
  assert.equal(shouldRegister({ status: "authenticated", platform: "ios" }), true);
  assert.equal(shouldRegister({ status: "authenticated", platform: "web" }), false);
  for (const status of ["loading", "anonymous", "unreachable"]) {
    assert.equal(shouldRegister({ status, platform: "android" }), false, status);
  }
});

test("toggleKind adds then removes and never mutates its input", () => {
  const start = ["billing"];
  const added = toggleKind(start, "schedule");
  assert.deepEqual(added, ["billing", "schedule"]);
  assert.deepEqual(start, ["billing"]);
  assert.deepEqual(toggleKind(added, "billing"), ["schedule"]);
  assert.deepEqual(toggleKind(undefined, "care"), ["care"]);
});

test("registerPushToken PUTs the token with platform and device label", async () => {
  await registerPushToken({ token: "ExponentPushToken[a]", platform: "android", deviceLabel: "시험 폰" });
  assert.equal(calls[0].url, "http://api.test/notifications/push-token");
  assert.equal(calls[0].method, "PUT");
  assert.deepEqual(JSON.parse(calls[0].body), {
    token: "ExponentPushToken[a]",
    platform: "android",
    device_label: "시험 폰",
  });
});

test("unregisterPushToken DELETEs the token", async () => {
  await unregisterPushToken("ExponentPushToken[a]");
  assert.equal(calls[0].method, "DELETE");
  assert.equal(calls[0].url, "http://api.test/notifications/push-token");
  assert.deepEqual(JSON.parse(calls[0].body), { token: "ExponentPushToken[a]" });
});

test("getPushSettings GETs and savePushSettings PUTs the settings", async () => {
  await getPushSettings();
  assert.equal(calls[0].url, "http://api.test/notifications/push-settings");
  assert.equal(calls[0].method, "GET");
  const settings = { enabled: false, preview_mode: "sender", muted_kinds: ["billing"], quiet_start: "22:00", quiet_end: "07:00" };
  await savePushSettings(settings);
  assert.equal(calls[1].method, "PUT");
  assert.deepEqual(JSON.parse(calls[1].body), settings);
});

test("quiet hours preset: on sets 22:00~07:00, off clears, state is read from the pair", () => {
  const base = { enabled: true, preview_mode: "full", muted_kinds: [], quiet_start: null, quiet_end: null };
  assert.equal(isQuietOn(base), false);
  const on = withQuiet(base, true);
  assert.deepEqual([on.quiet_start, on.quiet_end], ["22:00", "07:00"]);
  assert.equal(isQuietOn(on), true);
  assert.equal(isQuietOn({ ...on, quiet_start: "22:00:00", quiet_end: "07:00:00" }), true); // 서버는 초까지 돌려준다
  const off = withQuiet(on, false);
  assert.deepEqual([off.quiet_start, off.quiet_end], [null, null]);
  assert.equal(base.quiet_start, null); // 입력은 바꾸지 않는다
});

test("PREVIEW_OPTIONS lists the three server modes in order", () => {
  assert.deepEqual(
    PREVIEW_OPTIONS.map((o) => o.key),
    ["full", "sender", "hidden"],
  );
});

test("token tracker remembers a token and hands it out once for release", () => {
  const tracker = createTokenTracker();
  assert.equal(tracker.take(), null); // 기억한 게 없으면 null
  tracker.remember("ExponentPushToken[a]");
  assert.equal(tracker.current(), "ExponentPushToken[a]");
  assert.equal(tracker.take(), "ExponentPushToken[a]");
  assert.equal(tracker.take(), null);
});

test("token tracker marks a registration stale when a release happened meanwhile", () => {
  const tracker = createTokenTracker();
  const started = tracker.begin();
  assert.equal(tracker.isStale(started), false); // 중간에 해제가 없으면 그대로 유효
  tracker.take(); // 로그아웃(해제)이 먼저 지나갔다
  assert.equal(tracker.isStale(started), true);
  assert.equal(tracker.isStale(tracker.begin()), false); // 새로 시작한 등록은 유효
});
