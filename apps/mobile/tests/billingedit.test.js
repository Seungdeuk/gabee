// 앱의 지출 수정: 고칠 수 있는 지출 판단, 바뀐 값만 보내기, PATCH 호출 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { canEditExpense, expensePatch } from "../src/features/billing/format.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";
// 서버 주소는 불러올 때 읽으므로 환경변수를 정한 뒤에 불러온다
const { deleteExpense, updateExpense } = await import("../src/features/billing/api.js");

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("내가 낸 정산 전 지출만 고칠 수 있다", () => {
  assert.equal(canEditExpense({ paid_by: "me", settled: false }, "me"), true);
  assert.equal(canEditExpense({ paid_by: "me" }, "me"), true);
  assert.equal(canEditExpense({ paid_by: "other", settled: false }, "me"), false);
  assert.equal(canEditExpense({ paid_by: "me", settled: true }, "me"), false);
  // 내 id 를 아직 모르면(불러오는 중·실패) 버튼을 보이지 않는다
  assert.equal(canEditExpense({ paid_by: "me", settled: false }, undefined), false);
  assert.equal(canEditExpense({ paid_by: "me", settled: false }, null), false);
  assert.equal(canEditExpense({ paid_by: "", settled: false }, ""), false);
});

test("바뀐 값만 담고, 같으면 빈 객체", () => {
  const old = { title: "치과", amount: 50000, date: "2026-10-12" };
  assert.deepEqual(expensePatch(old, { ...old }), {});
  assert.deepEqual(expensePatch(old, { ...old, amount: 60000 }), { amount: 60000 });
  assert.deepEqual(expensePatch(old, { title: "치과 검진", amount: 50000, date: "2026-10-20" }), { title: "치과 검진", date: "2026-10-20" });
  assert.deepEqual(expensePatch(old, { title: "치과", amount: 50000, date: "2026-10-12" }), {});
});

test("updateExpense 는 PATCH /billing/expenses/{id} 로 바뀐 값을 보낸다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method, body: init?.body });
    return new Response(JSON.stringify({ id: "e1", title: "치과", amount: 60000, date: "2026-10-12" }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const out = await updateExpense("e1", { amount: 60000 });
  assert.equal(out.amount, 60000);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "PATCH");
  assert.match(calls[0].url, /\/billing\/expenses\/e1$/);
  assert.deepEqual(JSON.parse(calls[0].body), { amount: 60000 });
});

test("규칙에 어긋나면 서버 문구를 담은 오류가 난다", async () => {
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: "expense_not_editable", message: "정산하기를 마친 지출은 고칠 수 없어요" }), { status: 400, headers: { "Content-Type": "application/json" } });
  await assert.rejects(
    () => updateExpense("e1", { amount: 1 }),
    (e) => e.status === 400 && e.code === "expense_not_editable" && /정산하기를 마친/.test(e.message),
  );
});

test("deleteExpense 는 DELETE /billing/expenses/{id} 를 부르고, 규칙에 어긋나면 서버 문구를 담은 오류가 난다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method });
    return new Response(null, { status: 204 });
  };
  await deleteExpense("e1");
  assert.equal(calls[0].method, "DELETE");
  assert.match(calls[0].url, /\/billing\/expenses\/e1$/);
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: "expense_not_deletable", message: "내가 낸 지출만 지울 수 있어요" }), { status: 400, headers: { "Content-Type": "application/json" } });
  await assert.rejects(
    () => deleteExpense("e2"),
    (e) => e.status === 400 && e.code === "expense_not_deletable" && /내가 낸 지출만/.test(e.message),
  );
});
