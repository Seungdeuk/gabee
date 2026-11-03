// 데일리 체크 개발용 가상 가족 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_dev.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { DEV_FAMILY, withDevFamily } from "../src/features/schedule/daily/logic.js";
import { FAMILY_ITEMS_MOCK, FAMILY_PHONE_MOCK } from "../src/features/schedule/daily/mock.js";

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

test("가상 가족 모드가 꺼져 있고 개발 빌드가 아니면 실제 목록 그대로", () => {
  assert.equal(withDevFamily(onlyMe, false, false), onlyMe);
  assert.equal(withDevFamily(withSon, false), withSon);
});

test("플래그가 켜지면 가상 가족 다섯 명을 뒤에 덧붙인다", () => {
  assert.deepEqual(
    withDevFamily(withSon, true, false).map((m) => m.id),
    ["me", "u-son", ...DEV_IDS],
  );
});

test("개발 빌드이고 실제 가족이 없으면 플래그가 꺼져 있어도 가상 가족을 덧붙인다", () => {
  assert.deepEqual(withDevFamily(onlyMe, false, true).map((m) => m.id), ["me", ...DEV_IDS]);
  assert.deepEqual(withDevFamily([], false, true).map((m) => m.id), DEV_IDS);
});

test("개발 빌드라도 실제 가족이 있으면 플래그가 꺼져 있을 때 덧붙이지 않는다", () => {
  assert.deepEqual(withDevFamily(withSon, false, true).map((m) => m.id), ["me", "u-son"]);
});

test("실제 가족이 이미 mom·dad 를 가지면 중복으로 넣지 않고 실제 이름을 쓴다", () => {
  const withReal = [
    { id: "me", name: "나" },
    { id: "mom", name: "어머니" },
    { id: "dad", name: "아버지" },
  ];
  const merged = withDevFamily(withReal, true, false);
  assert.deepEqual(merged.map((m) => m.id), ["me", "mom", "dad", "son", "daughter", "gran"]);
  assert.equal(merged.find((m) => m.id === "mom").name, "어머니");
});

test("실제 가족에 mom 만 있으면 플래그가 켜졌을 때만 나머지를 더한다", () => {
  assert.deepEqual(withDevFamily(momOnly, false, true).map((m) => m.id), ["me", "mom"]);
  assert.deepEqual(withDevFamily(momOnly, true, true).map((m) => m.id), ["me", "mom", "dad", "son", "daughter", "gran"]);
});

test("가상 가족은 다섯 명이고 id 가 기록·전화 mock 과 맞는다", () => {
  assert.deepEqual(DEV_FAMILY.map((m) => m.id), DEV_IDS);
  assert.deepEqual(Object.keys(FAMILY_ITEMS_MOCK).sort(), [...DEV_IDS].sort());
  assert.deepEqual(Object.keys(FAMILY_PHONE_MOCK).sort(), [...DEV_IDS].sort());
});

test("가족 기록 mock: 사람마다 항목 개수가 달라 진행 라벨이 다양하다", () => {
  const counts = DEV_IDS.map((id) => FAMILY_ITEMS_MOCK[id].length);
  assert.equal(new Set(counts).size >= 3, true);
  const sizes = Object.values(FAMILY_ITEMS_MOCK).map((list) => list.length);
  assert.equal(Math.min(...sizes) >= 2, true);
});

test("전화 mock: 가린 번호의 끝 네 자리가 전화 번호와 같다", () => {
  for (const id of DEV_IDS) {
    const p = FAMILY_PHONE_MOCK[id];
    assert.match(p.masked, /^010-\*\*\*\*-\d{4}$/);
    assert.equal(p.dial.slice(-4), p.masked.slice(-4));
  }
});
