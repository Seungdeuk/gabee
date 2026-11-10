// 데일리 체크 점 표시 모드의 바깥 터치 종료(shouldHideDotsOnTouch): node --import ./tests/register-alias.mjs --test tests/schedule_daily_touch.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldHideDotsOnTouch } from "../src/features/schedule/daily/logic.js";

test("점 표시 모드가 아니면 아무 일도 없다", () => {
  assert.equal(shouldHideDotsOnTouch({ showDots: false, insideRow: false }), "none");
});

test("줄·점·메뉴 위를 누르면 그대로 둔다", () => {
  assert.equal(shouldHideDotsOnTouch({ showDots: true, insideRow: true }), "none");
});

test("줄·점·메뉴 밖을 누르면 점과 메뉴를 한 번에 닫는다", () => {
  assert.equal(shouldHideDotsOnTouch({ showDots: true, insideRow: false }), "hideAll");
});
