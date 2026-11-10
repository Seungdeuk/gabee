// 데일리 체크 개발용 가상 가족 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_dev.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { DEV_FAMILY, withDevFamily } from "../src/features/schedule/daily/logic.js";
import { FAMILY_ITEMS_MOCK } from "../src/features/schedule/daily/mock.js";

const DEV_IDS = ["mom", "dad", "son", "daughter", "gran"];
const onlyMe = [{ id: "me", name: "나" }];
const withSon = [
  { id: "me", name: "나" },
  { id: "u-son", name: "아들" },
];
const momOnly = [
  { id: "me", name: "나" },
  { id: "mom", name: "어머니" },
];

test("개발 빌드가 아니면 실제 목록 그대로(가상 가족을 넣지 않는다)", () => {
  assert.equal(withDevFamily(onlyMe, false), onlyMe);
  assert.equal(withDevFamily(withSon, false), withSon);
});

test("개발 빌드이고 실제 가족이 없으면(나만 있으면) 가상 가족 다섯 명을 덧붙인다", () => {
  assert.deepEqual(withDevFamily(onlyMe, true).map((m) => m.id), ["me", ...DEV_IDS]);
  assert.deepEqual(withDevFamily([], true).map((m) => m.id), DEV_IDS);
});

test("개발 빌드라도 실제 가족이 한 명이라도 있으면 가상 가족을 넣지 않는다", () => {
  assert.equal(withDevFamily(withSon, true), withSon);
  assert.deepEqual(withDevFamily(momOnly, true).map((m) => m.id), ["me", "mom"]);
});

test("가상 가족은 hasAccount 가 false 라서 화면이 읽기 전용으로 그린다", () => {
  for (const m of withDevFamily(onlyMe, true).slice(1)) {
    assert.equal(m.hasAccount, false);
  }
});

test("가상 가족은 다섯 명이고 id 가 기록 mock 과 맞는다", () => {
  assert.deepEqual(DEV_FAMILY.map((m) => m.id), DEV_IDS);
  assert.deepEqual(Object.keys(FAMILY_ITEMS_MOCK).sort(), [...DEV_IDS].sort());
});

test("가족 기록 mock: 사람마다 항목 개수가 달라 진행 라벨이 다양하다", () => {
  const counts = DEV_IDS.map((id) => FAMILY_ITEMS_MOCK[id].length);
  assert.equal(new Set(counts).size >= 3, true);
  const sizes = Object.values(FAMILY_ITEMS_MOCK).map((list) => list.length);
  assert.equal(Math.min(...sizes) >= 2, true);
});
