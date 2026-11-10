// 데일리 체크 온보딩 저장 흐름 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_onboard.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { onboardingChoices, onboardingToSave } from "../src/features/schedule/daily/logic.js";

const choices = onboardingChoices(["산책하기", "약 먹기", "혈압 재기", "스트레칭", "일기 쓰기"]);

test("고른 이름만 저장할 항목으로 만든다(알림은 끈 채로)", () => {
  const items = onboardingToSave(choices, ["물 마시기", "안부 전화"], []);
  assert.deepEqual(items.map((i) => i.name), ["물 마시기", "안부 전화"]);
  assert.ok(items.every((i) => i.alarm === false));
});

test("이미 있는 이름은 빼고 저장한다(중복 등록 방지)", () => {
  const items = onboardingToSave(choices, ["물 마시기", "영양제 먹기"], ["물 마시기"]);
  assert.deepEqual(items.map((i) => i.name), ["영양제 먹기"]);
});

test("고른 게 없거나 전부 이미 있으면 빈 목록", () => {
  assert.deepEqual(onboardingToSave(choices, [], []), []);
  assert.deepEqual(onboardingToSave(choices, ["알림장 확인"], ["알림장 확인"]), []);
});

test("고르지 않은 카드는 저장하지 않는다", () => {
  const items = onboardingToSave(choices, ["산책하기"], []);
  assert.deepEqual(items.map((i) => i.name), ["산책하기"]);
});
