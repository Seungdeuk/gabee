// 보낸 부탁 메모 바꾸기 시험(규칙·실패 문구·API 호출): node --import ./tests/register-alias.mjs --test tests/schedule_memo_edit.test.js
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { REQUEST_MEMO_MAX, memoChars, memoErrorMessage, memoGuide } from "../src/features/schedule/memo_edit.js";

// API 시험은 환경 변수를 본 뒤(client.js 가 읽을 때) 불러온다. 이 파일은 node 프로세스 하나에서 돈다.
process.env.EXPO_PUBLIC_API_URL = "http://api.test";
const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("글자 수: 이모지도 한 글자로 센다", () => {
  assert.equal(memoChars("가😀"), 2);
  assert.equal(memoChars(""), 0);
  assert.equal(memoChars(null), 0);
});

test("메모 시트: 바뀐 게 없으면 저장할 수 없다(앞뒤 공백만 다르면 같은 것)", () => {
  assert.deepEqual(memoGuide("과일 사기", "과일 사기"), { message: null, canSave: false });
  assert.deepEqual(memoGuide("과일 사기", "  과일 사기  "), { message: null, canSave: false });
  assert.deepEqual(memoGuide("", "   "), { message: null, canSave: false });
});

test("메모 시트: 바꾼 메모는 저장할 수 있다", () => {
  assert.deepEqual(memoGuide("과일 사기", "반찬도 사기"), { message: null, canSave: true });
  assert.deepEqual(memoGuide("", "새 메모"), { message: null, canSave: true });
});

test("메모 시트: 비우면 저장할 수 있고 지운다는 안내가 나온다", () => {
  assert.deepEqual(memoGuide("과일 사기", ""), { message: "메모를 비우면 메모가 지워져요", canSave: true });
  assert.deepEqual(memoGuide("과일 사기", "   "), { message: "메모를 비우면 메모가 지워져요", canSave: true });
});

test("메모 시트: 2000자까지는 저장되고, 넘으면 막는다", () => {
  assert.equal(REQUEST_MEMO_MAX, 2000);
  assert.equal(memoGuide("", "가".repeat(2000)).canSave, true);
  const over = memoGuide("", "가".repeat(2001));
  assert.equal(over.canSave, false);
  assert.equal(over.message, "메모는 2000자까지 쓸 수 있어요");
});

test("실패 문구: 403 은 보낸 사람만, 400 취소는 취소된 부탁, 422 는 글자 수, 나머지는 일반 문구", () => {
  assert.equal(memoErrorMessage({ status: 403, code: "not_owner" }), "보낸 사람만 메모를 고칠 수 있어요");
  assert.equal(memoErrorMessage({ status: 400, code: "request_canceled" }), "취소된 부탁은 메모를 고칠 수 없어요");
  assert.equal(memoErrorMessage({ status: 422, code: "error" }), "메모는 2000자까지 쓸 수 있어요");
  assert.equal(memoErrorMessage({ status: 0, code: "network_error" }), "메모를 바꾸지 못했어요. 잠시 뒤 다시 해 주세요");
  assert.equal(memoErrorMessage(undefined), "메모를 바꾸지 못했어요. 잠시 뒤 다시 해 주세요");
});

test("API: PUT /schedule/requests/{id}/memo 에 { memo } 를 보내고 응답을 돌려준다", async () => {
  const api = await import("../src/features/schedule/api.js");
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: new URL(url).pathname, method: init.method, body: JSON.parse(init.body) });
    return json(200, { id: "r1", memo: "반찬도 사기" });
  };
  const saved = await api.changeMemo("r1", "반찬도 사기");
  assert.deepEqual(calls, [{ url: "/schedule/requests/r1/memo", method: "PUT", body: { memo: "반찬도 사기" } }]);
  assert.equal(saved.memo, "반찬도 사기");
});

test("API: 빈 문자열은 그대로 보내 메모를 지운다", async () => {
  const api = await import("../src/features/schedule/api.js");
  let sent = null;
  globalThis.fetch = async (_url, init = {}) => {
    sent = JSON.parse(init.body);
    return json(200, { id: "r1", memo: "" });
  };
  await api.changeMemo("r1", "");
  assert.deepEqual(sent, { memo: "" });
});

test("API: 403 not_owner 는 ApiError 로 올라와 실패 문구로 이어진다", async () => {
  const api = await import("../src/features/schedule/api.js");
  globalThis.fetch = async () => json(403, { code: "not_owner", message: "x" });
  await assert.rejects(api.changeMemo("r1", "x"), (error) => {
    assert.equal(error.status, 403);
    assert.equal(error.code, "not_owner");
    assert.equal(memoErrorMessage(error), "보낸 사람만 메모를 고칠 수 있어요");
    return true;
  });
});
