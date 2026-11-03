// 데일리 체크 통화 뒤 시트 조건(shouldShowCallDone): node --import ./tests/register-alias.mjs --test tests/schedule_daily_call.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { ALL_DAYS, shouldShowCallDone } from "../src/features/schedule/daily/logic.js";

// 2026-11-02 은 월요일이다.
const TODAY = "2026-11-02";
const call = (over = {}) => ({ id: "call", name: "안부 전화", type: "check", goal: 1, unit: "", days: ALL_DAYS, ...over });

test("오늘 목록에 안부 전화 습관이 없으면 시트를 띄우지 않는다", () => {
  assert.equal(shouldShowCallDone([], {}, TODAY), false);
  assert.equal(shouldShowCallDone([{ id: "x", name: "물 마시기", type: "check", goal: 1, unit: "", days: ALL_DAYS }], {}, TODAY), false);
});

test("안부 전화 습관이 오늘 요일에 안 맞으면(오늘 목록에 없으면) 띄우지 않는다", () => {
  assert.equal(shouldShowCallDone([call({ days: ["sat"] })], {}, TODAY), false);
});

test("안부 전화 습관이 오늘 있고 아직 완료가 아니면 띄운다", () => {
  assert.equal(shouldShowCallDone([call()], {}, TODAY), true);
  assert.equal(shouldShowCallDone([call()], { call: { done: false } }, TODAY), true);
});

test("이미 오늘 완료했으면 띄우지 않는다", () => {
  assert.equal(shouldShowCallDone([call()], { call: { done: true, doneAt: "10:00" } }, TODAY), false);
});

test("이름에 안부 전화가 들어 있으면 해당한다(예: 가족 안부 전화)", () => {
  assert.equal(shouldShowCallDone([call({ name: "엄마 안부 전화" })], {}, TODAY), true);
});
