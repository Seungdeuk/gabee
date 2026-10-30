// 돌봄 데일리 체크에서 식사 항목을 숨기는 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { withoutMealItems } from "../src/features/care/format.js";

const daily = {
  date: "2026-10-30",
  now: "10:00",
  items: [
    { id: "m1", name: "아침 식사", meal_type: "breakfast" },
    { id: "v1", name: "영양제", meal_type: null },
    { id: "m2", name: "점심 식사", meal_type: "lunch" },
    { id: "w1", name: "물", meal_type: null },
  ],
  meals: [{ meal: "breakfast" }, { meal: "lunch" }],
  missing_ids: ["m1", "w1"],
  upcoming_ids: ["m2", "v1"],
  cleanup_ids: ["m1"],
  skipped_ids: [],
  done_ids: ["v1", "m2"],
};

test("식사 항목이 목록과 모든 상태 목록에서 빠진다", () => {
  const out = withoutMealItems(daily);
  assert.deepEqual(out.items.map((i) => i.id), ["v1", "w1"]);
  assert.deepEqual(out.missing_ids, ["w1"]);
  assert.deepEqual(out.upcoming_ids, ["v1"]);
  assert.deepEqual(out.cleanup_ids, []);
  assert.deepEqual(out.done_ids, ["v1"]);
  assert.deepEqual(out.meals, []);
});

test("원본은 바꾸지 않고, 날짜 같은 다른 값은 그대로 둔다", () => {
  const out = withoutMealItems(daily);
  assert.equal(daily.items.length, 4);
  assert.equal(out.date, "2026-10-30");
  assert.equal(out.now, "10:00");
});

test("식사 항목이 없으면 같은 객체를 돌려준다", () => {
  const plain = { ...daily, items: [{ id: "v1", name: "영양제", meal_type: null }], meals: [], missing_ids: [], upcoming_ids: [], cleanup_ids: [], skipped_ids: [], done_ids: [] };
  assert.equal(withoutMealItems(plain), plain);
});
