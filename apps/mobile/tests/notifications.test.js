// 알림함: API 경로·분류 표시와 이동 규칙·안 읽은 개수 실패 처리를 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { badgeLabel, relativeTime, safeTotal } from "../src/features/notifications/format.js";
import { KIND_META, KIND_ORDER, metaFor, routeFor } from "../src/features/notifications/kinds.js";

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
  await listNotifications({ kind: "billing", limit: 30, cursor: "abc" });
  assert.equal(calls.at(-1).url, "http://api.test/notifications?kind=billing&limit=30&cursor=abc");
  await listNotifications();
  assert.equal(calls.at(-1).url, "http://api.test/notifications");
  await getUnreadCount();
  assert.equal(calls.at(-1).url, "http://api.test/notifications/unread-count");
  await markRead("n1");
  assert.equal(calls.at(-1).method, "POST");
  assert.equal(calls.at(-1).url, "http://api.test/notifications/n1/read");
  await markAllRead("billing");
  assert.equal(calls.at(-1).url, "http://api.test/notifications/read-all");
  assert.deepEqual(JSON.parse(calls.at(-1).body), { kind: "billing" });
  await markAllRead();
  assert.equal(calls.at(-1).method, "POST");
});

test("분류 표시: 4개 분류 모두 이름·아이콘·색이 있고 모르는 분류도 깨지지 않는다", () => {
  for (const kind of ["schedule", "billing", "family_group", "support"]) {
    const meta = KIND_META[kind];
    assert.ok(meta.label && meta.icon && meta.color, kind);
  }
  for (const removed of ["care", "ai_record"]) assert.equal(KIND_META[removed], undefined, removed); // 돌봄·기록 분류는 없앴다
  assert.deepEqual(KIND_ORDER, ["schedule", "billing"]);
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

test("새 공유 일정·할 일 배정은 일정 탭으로, 정산·송금·용돈은 지갑(돌봄) 탭으로 이동하고 문서 알림은 읽음만 한다", () => {
  assert.equal(routeFor({ kind: "schedule", event: "event_shared" }), "/schedule");
  assert.equal(routeFor({ kind: "schedule", event: "todo_assigned" }), null); // 공동 할 일을 보는 화면이 앱에 아직 없다(읽음만)
  for (const event of ["settlement_updated", "payment_marked", "allowance_requested", "allowance_decided"]) {
    assert.equal(routeFor({ kind: "billing", event }), "/care");
  }
  assert.equal(routeFor({ kind: "billing", event: "something_new" }), null);
  assert.equal(routeFor({ kind: "ai_record", event: "document_added" }), null); // 없앤 분류는 이동 경로가 없다
  assert.equal(routeFor({ kind: "care", event: "x" }), null);
});

test("안 읽은 개수를 못 불러와도 0 이고 예외가 나지 않는다", async () => {
  assert.equal(await safeTotal(Promise.reject(new Error("offline"))), 0);
  assert.equal(await safeTotal(Promise.resolve({ total: 3, by_kind: {} })), 3);
  assert.equal(await safeTotal(Promise.resolve(null)), 0);
  assert.equal(await safeTotal(Promise.resolve({ total: "x" })), 0);
});

test("종 아이콘 배지: 0 이면 숨기고 100 이상은 99+", () => {
  assert.equal(badgeLabel(0), null);
  assert.equal(badgeLabel(-1), null);
  assert.equal(badgeLabel(7), "7");
  assert.equal(badgeLabel(99), "99");
  assert.equal(badgeLabel(100), "99+");
});

test("알림 시각: 방금·분·시간·일 전, 일주일이 넘으면 날짜", () => {
  const now = new Date("2026-10-28T12:00:00Z");
  const ago = (ms) => new Date(now.getTime() - ms).toISOString();
  assert.equal(relativeTime(ago(30 * 1000), now), "방금");
  assert.equal(relativeTime(ago(5 * 60 * 1000), now), "5분 전");
  assert.equal(relativeTime(ago(3 * 3600 * 1000), now), "3시간 전");
  assert.equal(relativeTime(ago(2 * 86400 * 1000), now), "2일 전");
  assert.equal(relativeTime("2026-10-01T09:00:00Z", now), "10월 1일");
  assert.equal(relativeTime("2026-10-28T11:55:00", now), "5분 전"); // 시간대 표시가 없으면 UTC 로 본다(임시 SQLite)
  assert.equal(relativeTime("not-a-date", now), "");
  assert.equal(relativeTime(ago(-5000), now), "방금"); // 시계가 어긋나 미래로 보여도 방금
});
