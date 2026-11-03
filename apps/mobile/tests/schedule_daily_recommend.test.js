// 데일리 체크 추천 칩 → 항목 추가 화면 흐름 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_recommend.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { RECOMMEND_POOL } from "../src/features/schedule/daily/mock.js";
import {
  draftFromParams,
  recommendAvailable,
  recommendChipLabel,
  recommendToForm,
} from "../src/features/schedule/daily/logic.js";

test("추천 칩을 누르면 넘길 값: 이름·체크 방식·목표 글자(문자열)", () => {
  const walk = RECOMMEND_POOL.find((p) => p.name === "산책하기");
  const params = recommendToForm(walk);
  assert.deepEqual(params, { name: "산책하기", type: "count", goalText: "30분" });
  assert.ok(Object.values(params).every((v) => typeof v === "string"));
});

test("라우트 params 에서 항목 추가 화면 처음 값을 읽는다", () => {
  assert.deepEqual(draftFromParams({ name: "약 먹기", type: "check", goalText: "1" }), {
    name: "약 먹기",
    type: "check",
    goalText: "1",
  });
  assert.deepEqual(draftFromParams({ name: "산책하기", type: "count", goalText: "30분" }), {
    name: "산책하기",
    type: "count",
    goalText: "30분",
  });
});

test("이름이 없으면 빈 화면(null), 모양이 이상하면 기본값", () => {
  assert.equal(draftFromParams({}), null);
  assert.equal(draftFromParams({ name: "   " }), null);
  assert.equal(draftFromParams(undefined), null);
  assert.deepEqual(draftFromParams({ name: "물", type: "bogus" }), { name: "물", type: "check", goalText: "1" });
  assert.deepEqual(draftFromParams({ name: "물", type: "count" }), { name: "물", type: "count", goalText: "8" });
});

test("추천에서 이미 있는 항목은 빠진다(등록한 칩은 사라진다)", () => {
  const before = recommendAvailable(RECOMMEND_POOL, [], 3).map((p) => p.name);
  assert.deepEqual(before, ["산책하기", "약 먹기", "혈압 재기"]);
  const after = recommendAvailable(RECOMMEND_POOL, ["산책하기"], 3).map((p) => p.name);
  assert.deepEqual(after, ["약 먹기", "혈압 재기", "스트레칭"]);
});

test("칩 글자: 목표가 있으면 '이름 · 목표'", () => {
  assert.equal(recommendChipLabel({ name: "산책하기", goal: 30, unit: "분" }), "산책하기 · 30분");
  assert.equal(recommendChipLabel({ name: "약 먹기" }), "약 먹기");
});
