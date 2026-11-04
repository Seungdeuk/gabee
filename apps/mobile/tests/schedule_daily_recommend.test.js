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
import { cheerSuggestionsFromServer, habitSuggestionsFromServer } from "../src/features/schedule/daily/serverMap.js";

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

// ── 서버 추천(DB 창고) 변환 ──

test("서버 추천 습관: 체크는 이름만, 횟수는 목표·단위까지", () => {
  const got = habitSuggestionsFromServer([
    { name: "약 먹기", kind: 1, goal: null, unit: null },
    { name: "물 마시기", kind: 2, goal: 8, unit: "잔" },
  ]);
  assert.deepEqual(got, [{ name: "약 먹기" }, { name: "물 마시기", goal: 8, unit: "잔" }]);
  assert.deepEqual(recommendToForm(got[1]), { name: "물 마시기", type: "count", goalText: "8잔" });
});

test("서버 추천 습관: 이름이 길거나 모양이 이상한 줄은 버리고, 목표 없는 횟수는 체크로 본다", () => {
  const got = habitSuggestionsFromServer([
    { name: "가".repeat(21), kind: 1 },
    { name: "  ", kind: 1 },
    { kind: 1 },
    null,
    { name: "걷기", kind: 2, goal: null, unit: "분" },
  ]);
  assert.deepEqual(got, [{ name: "걷기" }]);
  assert.deepEqual(habitSuggestionsFromServer(undefined), []);
});

test("서버 추천 응원 문구: 비었거나 50자를 넘는 줄은 버린다", () => {
  const got = cheerSuggestionsFromServer([
    { message: " 오늘도 정말 잘하셨어요 " },
    { message: "" },
    { message: "가".repeat(51) },
    { message: "가".repeat(50) },
    {},
  ]);
  assert.deepEqual(got, ["오늘도 정말 잘하셨어요", "가".repeat(50)]);
  assert.deepEqual(cheerSuggestionsFromServer(null), []);
});
