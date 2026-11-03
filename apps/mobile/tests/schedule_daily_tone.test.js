// 데일리 체크 응원 종류별 색 · 닫기 · 선택 색 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_tone.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DAY_PRESETS,
  SELECT_BG,
  SELECT_BORDER,
  allCheersHandled,
  cheerTone,
  openCheersOf,
  cheerCaption,
  recommendChipLabel,
  recommendAvailable,
  recommendToForm,
} from "../src/features/schedule/daily/logic.js";
import { avatarPalette, colors } from "../src/theme/index.js";

const TODAY = "2026-11-02";
const received = (over) => ({ id: "x", direction: "received", fromName: "아들", kind: "love", text: "t", date: TODAY, time: "16:02", thanked: false, ...over });

test("사랑해요 = 복숭아(바탕 #FFEDE5, 테두리 #F6CDBE, 아이콘·진한색 #C2503A)", () => {
  assert.deepEqual(cheerTone("love"), { bg: "#FFEDE5", border: "#F6CDBE", icon: "#C2503A", strong: "#C2503A", text: "#C2503A" });
});

test("최고예요 = 하늘(바탕 #E6F0F8, 테두리 #C9DDEE, 아이콘·진한색 #3A6E99)", () => {
  assert.deepEqual(cheerTone("best"), { bg: "#E6F0F8", border: "#C9DDEE", icon: "#3A6E99", strong: "#3A6E99", text: "#3A6E99" });
});

test("잘하셨어요 = 노랑(바탕 #FEF0CC, 테두리 #F2D58E, 아이콘·진한색 #B7791C, 글자 #8A5A2B)", () => {
  assert.deepEqual(cheerTone("well"), { bg: "#FEF0CC", border: "#F2D58E", icon: "#B7791C", strong: "#B7791C", text: "#8A5A2B" });
});

test("추천: 이미 있는 이름은 빼고 앞에서 세 개만, 다 있으면 빈 목록(넘기기 없음)", () => {
  const pool = [{ name: "a" }, { name: "b" }, { name: "c" }, { name: "d" }];
  assert.deepEqual(recommendAvailable(pool, ["b"]).map((p) => p.name), ["a", "c", "d"]);
  assert.deepEqual(recommendAvailable(pool, ["a"], 2).map((p) => p.name), ["b", "c"]);
  assert.deepEqual(recommendAvailable(pool, ["a", "b", "c", "d"]), []);
  assert.deepEqual(recommendAvailable(pool, []).length, 3);
});

test("추천 칩 글자와 고르면 채울 폼 값", () => {
  const walk = { name: "산책하기", goal: 30, unit: "분" };
  assert.equal(recommendChipLabel(walk), "산책하기 · 30분");
  assert.equal(recommendChipLabel({ name: "약 먹기" }), "약 먹기");
  assert.deepEqual(recommendToForm(walk), { name: "산책하기", type: "count", goalText: "30분" });
  assert.deepEqual(recommendToForm({ name: "약 먹기" }), { name: "약 먹기", type: "check", goalText: "1" });
});

test("알 수 없는 종류는 복숭아 계열로 본다", () => {
  assert.deepEqual(cheerTone("nope"), cheerTone("love"));
});

test("선택 색은 노란 바탕 #FEECBF 과 1px #F6D06B 테두리", () => {
  assert.equal(SELECT_BG, colors.surfaceStrong);
  assert.equal(SELECT_BORDER, avatarPalette[1].backgroundColor);
  assert.equal(SELECT_BORDER.toUpperCase(), "#F6D06B");
});

test("반복 빠른 선택 칩 순서와 글자: 모두 / 평일 / 주말 / 해제", () => {
  assert.deepEqual(DAY_PRESETS.map((p) => p.label), ["모두", "평일", "주말", "해제"]);
});

test("닫은 카드는 메인 카드에서 빠지고, 고마워 처리와는 따로 본다", () => {
  const list = [received({ id: "a" }), received({ id: "b", fromName: "딸" })];
  assert.deepEqual(openCheersOf(list, TODAY, ["a"]).map((c) => c.id), ["b"]);
  assert.equal(cheerCaption(list, TODAY, ["a"]), "오늘 받은 응원 1 / 2");
  // 닫은 카드는 고마워 보냄이 되지 않는다(thanked 는 그대로 false)
  assert.equal(list[0].thanked, false);
});

test("모두 처리(고마워 또는 닫기)하면 배너 조건이 된다", () => {
  const list = [received({ id: "a" }), received({ id: "b", fromName: "딸", thanked: true })];
  assert.equal(allCheersHandled(list, TODAY, []), false);
  assert.equal(allCheersHandled(list, TODAY, ["a"]), true);
  assert.equal(allCheersHandled([], TODAY, []), false);
});
