// 읽음 표시·안 읽은 수: 순수 함수와 API 경로·본문을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { flushTarget, nextPollDelay, readStatesDue, shouldMarkRead, unreadCount } from "../src/features/family-chat/chatUtils.js";
import { trackMarkRead, waitForPendingMarkRead } from "../src/features/family-chat/pendingRead.js";
import { roomA11yLabel, unreadBadgeText, unreadByA11yLabel } from "../src/features/family-chat/listUtils.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const mine = (id) => ({ id, user_id: "me", text: "x", created_at: "2026-10-23T06:00:00Z" });
const other = (id) => ({ id, user_id: "dad", text: "x", created_at: "2026-10-23T06:00:00Z" });
const state = (user_id, last_read_message_id) => ({ user_id, last_read_message_id });
const me = { id: "me", name: "나" };

test("unreadCount: 모두 읽음이면 0, 일부만 읽었으면 안 읽은 사람 수", () => {
  const all = [state("me", 5), state("dad", 10), state("mom", 10)];
  assert.equal(unreadCount(mine(10), me, all), 0); // 경계: last_read == id 는 읽음
  const some = [state("me", 10), state("dad", 10), state("mom", 9)];
  assert.equal(unreadCount(mine(10), me, some), 1);
  const none = [state("me", 10), state("dad", 0), state("mom", 3)];
  assert.equal(unreadCount(mine(10), me, none), 2);
});

test("unreadCount: 나만 있는 가족, 내 읽음 위치는 세지 않는다", () => {
  assert.equal(unreadCount(mine(3), me, [state("me", 0)]), 0);
  assert.equal(unreadCount(mine(3), me, []), 0);
  assert.equal(unreadCount(mine(3), me, null), 0);
});

test("unreadCount: 임시·실패 메시지와 상대 메시지는 표시하지 않는다(0)", () => {
  const states = [state("me", 0), state("dad", 0)];
  assert.equal(unreadCount({ ...mine("tmp-1"), clientId: "tmp-1", status: "sending" }, me, states), 0);
  assert.equal(unreadCount({ ...mine("tmp-2"), clientId: "tmp-2", status: "failed" }, me, states), 0);
  assert.equal(unreadCount(other(4), me, states), 0);
  assert.equal(unreadCount(mine(4), null, states), 0);
});

test("unreadCount: 읽음 상태를 못 받았으면(null) 0, 이탈 구성원은 응답에 없으니 세지 않는다", () => {
  assert.equal(unreadCount(mine(9), me, null), 0); // 깜빡임 방지: 미수신이면 숨김
  assert.equal(unreadCount(mine(9), me, undefined), 0);
  // 나간 구성원(mom)은 서버 응답에 없으므로 영구 안 읽음으로 세지 않는다
  assert.equal(unreadCount(mine(9), me, [state("me", 9), state("dad", 9)]), 0);
  assert.equal(unreadCount(mine(9), "me", [state("me", 9), state("dad", 8)]), 1); // id 문자열도 받는다
});

test("unreadCount: 나만 있는 가족은 0", () => {
  assert.equal(unreadCount(mine(5), me, [state("me", 0)]), 0);
});

test("nextPollDelay: 메시지 조회 실패 횟수만으로 정한다", () => {
  assert.equal(nextPollDelay(0), 3000);
  assert.equal(nextPollDelay(1), 6000);
  assert.equal(nextPollDelay(2), 12000);
  assert.equal(nextPollDelay(10), 30000);
});

test("readStatesDue: 실패 없으면 매 틱, 실패 n 번이면 2^n 틱(최대 10)마다", () => {
  assert.equal(readStatesDue(1, 0), true);
  assert.equal(readStatesDue(1, 1), false);
  assert.equal(readStatesDue(2, 1), true);
  assert.equal(readStatesDue(3, 2), false);
  assert.equal(readStatesDue(4, 2), true);
  assert.equal(readStatesDue(9, 5), false); // 32 → 최대 10
  assert.equal(readStatesDue(10, 5), true);
});

test("flushTarget: 대기 중인 값이 올린 값보다 크고 보내는 중이 아닐 때만", () => {
  assert.equal(flushTarget(10, 5, 0), 10);
  assert.equal(flushTarget(10, 10, 0), 0);
  assert.equal(flushTarget(10, 5, 10), 0); // 이미 그 id 를 보내는 중
  assert.equal(flushTarget(0, 0, 0), 0);
});

test("waitForPendingMarkRead: 진행 중 호출이 끝나면 풀리고, 실패해도 던지지 않는다", async () => {
  await waitForPendingMarkRead(); // 없으면 즉시
  let done = false;
  trackMarkRead(new Promise((_, reject) => setTimeout(() => { done = true; reject(new Error("x")); }, 20))).catch(() => {});
  await waitForPendingMarkRead();
  assert.equal(done, true);
  trackMarkRead(new Promise(() => {})); // 끝나지 않아도
  const t = Date.now();
  await waitForPendingMarkRead(50);
  assert.ok(Date.now() - t < 1000);
});

test("shouldMarkRead: 보일 때만, 올린 값보다 커졌을 때만", () => {
  assert.equal(shouldMarkRead(10, 0, true), true);
  assert.equal(shouldMarkRead(10, 9, true), true);
  assert.equal(shouldMarkRead(10, 10, true), false); // 같은 id 중복 호출 금지
  assert.equal(shouldMarkRead(8, 10, true), false);
  assert.equal(shouldMarkRead(10, 0, false), false); // 화면이 안 보이거나 앱이 뒤에 있으면 안 올림
  assert.equal(shouldMarkRead(0, 0, true), false); // 서버 메시지가 없으면 안 올림
});

test("unreadBadgeText: 0 은 숨김, 99 초과는 99+", () => {
  assert.equal(unreadBadgeText(0), "");
  assert.equal(unreadBadgeText(-1), "");
  assert.equal(unreadBadgeText(undefined), "");
  assert.equal(unreadBadgeText(1), "1");
  assert.equal(unreadBadgeText(99), "99");
  assert.equal(unreadBadgeText(100), "99+");
  assert.equal(unreadBadgeText(1000), "99+");
});

test("접근성 라벨: 안 읽은 수를 포함", () => {
  assert.equal(unreadByA11yLabel(2), "아직 2명이 읽지 않았어요");
  assert.equal(roomA11yLabel("안녕"), "가족 채팅방, 마지막 메시지 안녕");
  assert.equal(roomA11yLabel("안녕", 3), "가족 채팅방, 안 읽은 메시지 3개, 마지막 메시지 안녕");
  assert.equal(roomA11yLabel("안녕", 150), "가족 채팅방, 안 읽은 메시지 99+개, 마지막 메시지 안녕");
});

test("읽음 API: 경로·본문(대화 글자 없음), Bearer 만", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({ path: u.pathname, search: u.search, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} });
    if (u.pathname.endsWith("/read-states")) return json(200, [state("me", 3)]);
    if (u.pathname.endsWith("/unread")) return json(200, { unread: 2, last_read_message_id: 3 });
    return json(200, { last_read_message_id: 7 });
  };
  const client = await import("../src/shared/api/client.js");
  const api = await import("../src/features/family-chat/api.js");
  client.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  assert.deepEqual(await api.markRead(7), { last_read_message_id: 7 });
  assert.deepEqual(await api.getReadStates(), [state("me", 3)]);
  assert.deepEqual(await api.getUnread(), { unread: 2, last_read_message_id: 3 });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.path}`),
    ["POST /family-chat/read", "GET /family-chat/read-states", "GET /family-chat/unread"],
  );
  assert.deepEqual(calls[0].body, { message_id: 7 });
  assert.ok(calls.every((c) => c.search === ""));
  assert.equal(calls[1].body, null);
  assert.equal(calls[2].body, null);
  assert.ok(calls.every((c) => c.headers.Authorization === "Bearer access-1" && c.headers["X-Gyeot-Token"] === undefined));
});
