// 데일리 체크 가족 순서 위/아래 한 칸 이동 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_tabmove.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { moveTab, tabArrowDisabled } from "../src/features/schedule/daily/logic.js";

const tabs = { order: ["mom", "dad", "son"], hidden: [] };

test("위로 한 칸, 아래로 한 칸 이동", () => {
  assert.deepEqual(moveTab(tabs, "dad", -1).order, ["dad", "mom", "son"]);
  assert.deepEqual(moveTab(tabs, "dad", 1).order, ["mom", "son", "dad"]);
});

test("첫 칸에서 위, 끝 칸에서 아래는 그대로", () => {
  assert.equal(moveTab(tabs, "mom", -1), tabs);
  assert.equal(moveTab(tabs, "son", 1), tabs);
});

test("숨긴 탭은 건너뛰고 보이는 탭끼리 옮긴다", () => {
  const t = { order: ["mom", "dad", "son"], hidden: ["dad"] };
  assert.deepEqual(moveTab(t, "son", -1).order, ["son", "dad", "mom"]);
});

test("없는 id 는 그대로", () => {
  assert.equal(moveTab(tabs, "nobody", -1), tabs);
});

test("화살표 비활성: 첫 칸의 위, 끝 칸의 아래만 꺼진다", () => {
  assert.equal(tabArrowDisabled(tabs, "mom", -1), true);
  assert.equal(tabArrowDisabled(tabs, "mom", 1), false);
  assert.equal(tabArrowDisabled(tabs, "son", 1), true);
  assert.equal(tabArrowDisabled(tabs, "son", -1), false);
  assert.equal(tabArrowDisabled(tabs, "nobody", 1), true);
});
