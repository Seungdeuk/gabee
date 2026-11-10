// 데일리 체크 항목 위/아래 한 칸 이동 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_items_move.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { itemArrowDisabled, moveItemOne } from "../src/features/schedule/daily/logic.js";

const list = [{ id: "a" }, { id: "b" }, { id: "c" }];

test("위·아래 한 칸 이동", () => {
  assert.deepEqual(moveItemOne(list, "b", -1).map((x) => x.id), ["b", "a", "c"]);
  assert.deepEqual(moveItemOne(list, "b", 1).map((x) => x.id), ["a", "c", "b"]);
});

test("첫 칸의 위, 끝 칸의 아래는 그대로", () => {
  assert.equal(moveItemOne(list, "a", -1), list);
  assert.equal(moveItemOne(list, "c", 1), list);
});

test("없는 id 는 그대로", () => {
  assert.equal(moveItemOne(list, "zz", -1), list);
});

test("화살표 비활성: 첫 칸의 위, 끝 칸의 아래, 없는 id", () => {
  assert.equal(itemArrowDisabled(list, "a", -1), true);
  assert.equal(itemArrowDisabled(list, "a", 1), false);
  assert.equal(itemArrowDisabled(list, "c", 1), true);
  assert.equal(itemArrowDisabled(list, "c", -1), false);
  assert.equal(itemArrowDisabled(list, "zz", 1), true);
});
