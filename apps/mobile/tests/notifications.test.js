// 알림함: API 경로·분류 표시와 이동 규칙·안 읽은 개수 실패 처리를 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { safeTotal } from "../src/features/notifications/format.js";
import { KIND_META, metaFor, routeFor } from "../src/features/notifications/kinds.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";
// 서버 주소는 불러올 때 읽으므로 환경 변수를 정한 뒤에 가져온다
const { getUnreadCount, listNotifications, markAllRead, markRead } = await import("../src/features/notifications/api.js");

const realFetch = globalThis.fetch;
const calls = [];
beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    return new Response(JSON.stringify({ items: [], next_cursor: null, total: 0, by_kind: {}, updated: 0, id: "n1" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("알림 API 경로: 목록·개수·읽음·전부 읽음", async () => {
  await listNotifications({ kind: "care", limit: 30, cursor: "abc" });
  assert.equal(calls.at(-1).url, "http://api.test/notifications?kind=care&limit=30&cursor=abc");
  await listNotifications();
  assert.equal(calls.at(-1).url, "http://api.test/notifications");
  await getUnreadCount();
  assert.equal(calls.at(-1).url, "http://api.test/notifications/unread-count");
  await markRead("n1");
  assert.equal(calls.at(-1).method, "POST");
  assert.equal(calls.at(-1).url, "http://api.test/notifications/n1/read");
  await markAllRead("care");
  assert.equal(calls.at(-1).url, "http://api.test/notifications/read-all");
  assert.deepEqual(JSON.parse(calls.at(-1).body), { kind: "care" });
  await markAllRead();
  assert.equal(calls.at(-1).method, "POST");
});

test("분류 표시: 5개 분류 모두 이름·아이콘·색이 있고 모르는 분류도 깨지지 않는다", () => {
  for (const kind of ["schedule", "billing", "care", "family_group", "ai_record"]) {
    const meta = KIND_META[kind];
    assert.ok(meta.label && meta.icon && meta.color, kind);
  }
  assert.equal(metaFor("schedule").label, "일정");
  assert.equal(metaFor("unknown").label, "알림");
  assert.ok(metaFor(undefined).icon);
});

test("알림을 누르면 이동할 곳", () => {
  assert.equal(routeFor({ kind: "family_group", event: "join_requested" }), "/family-requests");
  assert.equal(routeFor({ kind: "family_group", event: "join_approved" }), "/family");
  assert.equal(routeFor({ kind: "family_group", event: "something_new" }), null);
  assert.equal(routeFor({ kind: "schedule", event: "event_created" }), null);
  assert.equal(routeFor(null), null);
});

test("안 읽은 개수를 못 불러와도 0 이고 예외가 나지 않는다", async () => {
  assert.equal(await safeTotal(Promise.reject(new Error("offline"))), 0);
  assert.equal(await safeTotal(Promise.resolve({ total: 3, by_kind: {} })), 3);
  assert.equal(await safeTotal(Promise.resolve(null)), 0);
  assert.equal(await safeTotal(Promise.resolve({ total: "x" })), 0);
});
