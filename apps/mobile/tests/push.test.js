// 푸시: 토큰 형식·등록 조건·푸시 탭 이동·분류 켜기/끄기와 푸시 API 경로를 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  PUSH_CHANNEL_ID,
  createTokenTracker,
  isQuietOn,
  isUsableToken,
  routeForPush,
  permissionNotice,
  permissionState,
  shouldRegister,
  toggleKind,
  withQuiet,
} from "../src/features/notifications/push.js";
import { KIND_META, KIND_ORDER } from "../src/features/notifications/kinds.js";

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

test("routeForPush: 알림함 사건은 알림함으로, 소통 푸시는 채팅방을 여는 길로 간다", () => {
  assert.equal(routeForPush(undefined), "/notifications");
  assert.equal(routeForPush(null), "/notifications");
  assert.equal(routeForPush({ kind: "schedule", notification_id: "n1" }), "/notifications");
  assert.equal(routeForPush({ kind: "chat", room_id: "ab12cd34ef56" }), "/chat-open?roomId=ab12cd34ef56");
  assert.equal(routeForPush({ kind: "chat", room_id: "a b&c" }), "/chat-open?roomId=a%20b%26c"); // 값은 주소에 안전하게 담는다
  assert.equal(routeForPush({ kind: "chat" }), "/family-chat"); // 방 id 가 없으면 소통 탭 목록
  assert.equal(routeForPush({ kind: "schedule", event: "event_soon" }), "/schedule"); // 예약 푸시는 일정 탭으로
  assert.equal(routeForPush({ kind: "schedule", event: "todo_due" }), "/schedule");
  assert.equal(routeForPush({ kind: "schedule", event: "request_received" }), "/notifications"); // 알림함 사건은 그대로
  assert.equal(routeForPush({ kind: "chat", room_id: 7 }), "/family-chat"); // 문자열이 아니면 믿지 않는다
});

test("chat 은 푸시 설정에서 끌 수 있는 분류로 표시된다(알림함 칩에는 없다)", () => {
  assert.equal(KIND_META.chat.label, "소통");
  assert.equal(KIND_ORDER.includes("chat"), false);
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
  assert.deepEqual(toggleKind(undefined, "schedule"), ["schedule"]);
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

test("알림 설정 화면: 소통 항목이 있고 더는 쓸모없는 '메시지 내용 표시 방식' 선택은 없다", async () => {
  const { readFileSync } = await import("node:fs");
  const screen = readFileSync(new URL("../src/features/notifications/screens/PushSettingsScreen.js", import.meta.url), "utf8");
  assert.match(screen, /const KIND_KEYS = \["chat", /);
  assert.doesNotMatch(screen, /PREVIEW_OPTIONS|Segmented|preview_mode: /);
  assert.match(screen, /새 메시지가 도착했어요/);
});

test("permissionState: 기기 알림 권한을 허용됨·물어볼 수 있음·막힘·알 수 없음으로 나눈다", () => {
  assert.equal(permissionState({ status: "granted", canAskAgain: true }), "granted");
  assert.equal(permissionState({ status: "undetermined", canAskAgain: true }), "ask");
  assert.equal(permissionState({ status: "denied", canAskAgain: true }), "ask"); // 아직 시스템 창을 다시 띄울 수 있다
  assert.equal(permissionState({ status: "denied", canAskAgain: false }), "blocked"); // 기기 설정에서만 켤 수 있다
  assert.equal(permissionState(null), "unknown");
  assert.equal(permissionState(undefined), "unknown");
  assert.equal(permissionState({}), "unknown");
});

test("permissionNotice: 푸시를 켜 둔 상태에서만, 상태별 안내와 버튼을 돌려준다", () => {
  assert.equal(permissionNotice("granted", true), null);
  assert.equal(permissionNotice("unknown", true), null);
  assert.equal(permissionNotice("blocked", false), null); // 푸시를 꺼 둔 사람에게는 권한 이야기를 하지 않는다
  assert.equal(permissionNotice("ask", true).action, "allow");
  assert.equal(permissionNotice("blocked", true).action, "settings");
  assert.equal(permissionNotice("failed", true).action, null);
  for (const state of ["ask", "blocked", "failed"]) assert.ok(permissionNotice(state, true).text.length > 0);
});

test("알림 설정 화면: 스위치를 켜면 이 기기 권한·토큰을 준비하고, 권한이 막혔으면 기기 설정을 열며, 돌아오면 다시 확인한다", async () => {
  const { readFileSync } = await import("node:fs");
  const read = (rel) => readFileSync(new URL(`../src/features/notifications/${rel}`, import.meta.url), "utf8");
  const screen = read("screens/PushSettingsScreen.js");
  assert.match(screen, /if \(next\.enabled && !previous\?\.enabled\) allowOnDevice\(\)/); // 방금 켠 때만
  assert.match(screen, /Linking\.openSettings\(\)/); // 권한이 막혔을 때
  assert.match(screen, /AppState\.addEventListener\("change"/); // 기기 설정에서 돌아오면
  assert.match(screen, /state === "granted" \? await prepareThisDevice\(\) : state/); // 허용돼 있을 때만 조용히 토큰 등록(묻지 않음)
  const boot = read("PushBootstrap.js");
  assert.match(boot, /export async function prepareThisDevice\(\)/);
  assert.match(boot, /export async function readPermissionState\(\)/);
  assert.doesNotMatch(read("messages.js"), /메시지 내용이 보일 수 있어요/); // 고정 문구 방침과 맞지 않는 안내가 없다
});
