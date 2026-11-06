import assert from "node:assert/strict";
import test from "node:test";

import { PAUSE_OPTIONS, pauseDays } from "../src/features/location/pause.js";

test("PAUSE_OPTIONS: 1일·3일·7일 다음에 기타", () => {
  assert.deepEqual(PAUSE_OPTIONS.map((o) => o.label), ["1일", "3일", "7일", "기타"]);
});

test("pauseDays: 고정 기간은 그대로", () => {
  assert.deepEqual(pauseDays("1", ""), { days: 1, error: "" });
  assert.deepEqual(pauseDays("7", "99"), { days: 7, error: "" }); // 기타 입력칸의 값은 무시한다
});

test("pauseDays: 기타는 1~14 정수만 받는다", () => {
  assert.deepEqual(pauseDays("other", "10"), { days: 10, error: "" });
  assert.deepEqual(pauseDays("other", " 14 "), { days: 14, error: "" });
  assert.equal(pauseDays("other", "").days, null);
  assert.equal(pauseDays("other", "0").days, null);
  assert.equal(pauseDays("other", "15").days, null);
  assert.equal(pauseDays("other", "3.5").days, null);
  assert.equal(pauseDays("other", "삼").days, null);
  assert.ok(pauseDays("other", "15").error.includes("1~14"));
});
