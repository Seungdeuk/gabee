// 정산 재알림 확인 호출(앱 홈을 열 때)의 경로·메서드를 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";
// 서버 주소는 불러올 때 읽으므로 환경변수를 정한 뒤에 불러온다
const { checkSettlementReminders } = await import("../src/features/billing/api.js");

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("재알림 확인은 POST /billing/settlement/reminders/check 를 부르고 created 를 돌려준다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method });
    return new Response(JSON.stringify({ created: 1 }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const res = await checkSettlementReminders();
  assert.deepEqual(res, { created: 1 });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.match(calls[0].url, /\/billing\/settlement\/reminders\/check$/);
});

test("서버가 실패하면 예외를 던진다(홈에서는 잡아서 무시한다)", async () => {
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: "db_unavailable", message: "x" }), { status: 503, headers: { "Content-Type": "application/json" } });
  await assert.rejects(
    () => checkSettlementReminders(),
    (e) => e.status === 503 && e.code === "db_unavailable",
  );
});
