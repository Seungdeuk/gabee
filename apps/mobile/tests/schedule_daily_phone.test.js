// 데일리 체크 전화 버튼 표시 판정 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_phone.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldShowCallButton } from "../src/features/schedule/daily/logic.js";

test("안드로이드는 canOpenURL 결과와 상관없이 전화 버튼을 보인다", () => {
  assert.equal(shouldShowCallButton("android", true), true);
  assert.equal(shouldShowCallButton("android", false), true);
  assert.equal(shouldShowCallButton("android", null), true);
});

test("iOS 는 canOpenURL 결과를 따른다: 열 수 있으면 보이고 거짓이면 숨긴다", () => {
  assert.equal(shouldShowCallButton("ios", true), true);
  assert.equal(shouldShowCallButton("ios", false), false);
});

test("확인 전(null)에는 어느 플랫폼이든 보인다", () => {
  assert.equal(shouldShowCallButton("ios", null), true);
  assert.equal(shouldShowCallButton("ios", undefined), true);
  assert.equal(shouldShowCallButton("web", null), true);
});
