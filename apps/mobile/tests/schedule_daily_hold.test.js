// 데일리 체크 꾹 누르기 판정(가족 순서·편집 화면 끌기): node --import ./tests/register-alias.mjs --test tests/schedule_daily_hold.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { HOLD_CANCEL_PX, holdDecision } from "../src/features/schedule/daily/logic.js";

test("취소 거리는 10px", () => {
  assert.equal(HOLD_CANCEL_PX, 10);
});

test("꾹 누름이 끝났으면(armed) 움직임과 상관없이 같은 터치로 끈다", () => {
  assert.equal(holdDecision({ armed: true, moved: 0 }), "activate");
  assert.equal(holdDecision({ armed: true, moved: 300 }), "activate");
});

test("꾹 누르기 전에 10px을 넘게 움직이면 취소(스크롤에 양보)", () => {
  assert.equal(holdDecision({ armed: false, moved: 11 }), "fail");
  assert.equal(holdDecision({ armed: false, moved: 50 }), "fail");
});

test("10px 이하로 살짝 움직인 것은 아직 기다린다", () => {
  assert.equal(holdDecision({ armed: false, moved: 0 }), "wait");
  assert.equal(holdDecision({ armed: false, moved: 10 }), "wait"); // 경계는 넘지 않는다
});
