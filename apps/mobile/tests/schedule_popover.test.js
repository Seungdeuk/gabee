// 칩 말풍선·삭제 버튼 위치 계산 시험: node --import ./tests/register-alias.mjs --test tests/schedule_popover.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { POPOVER_MARGIN, popoverPosition } from "../src/features/schedule/popover.js";

const screen = { screenWidth: 360, screenHeight: 800 };
const chip = (x, y = 300) => ({ x, y, width: 60, height: 28 });

test("칩 가운데에 맞춰 칩 아래에 틈 없이 붙는다", () => {
  const p = popoverPosition({ anchor: chip(150), width: 200, height: 100, ...screen });
  assert.equal(p.left, 80); // 중심 180 - 100
  assert.equal(p.top, 300 + 28);
  assert.equal(p.placement, "below");
});

test("왼쪽·오른쪽 화면 밖이면 안쪽으로 밀린다", () => {
  const l = popoverPosition({ anchor: chip(0), width: 200, height: 100, ...screen });
  assert.equal(l.left, POPOVER_MARGIN);
  const r = popoverPosition({ anchor: chip(300), width: 200, height: 100, ...screen });
  assert.equal(r.left, 360 - 200 - POPOVER_MARGIN);
});

test("위쪽 배치는 칩 위에 붙고, 자리가 없으면 뒤집는다", () => {
  const above = popoverPosition({ anchor: chip(150), width: 56, height: 30, placement: "above", ...screen });
  assert.equal(above.top, 300 - 30);
  assert.equal(above.placement, "above");
  const flip = popoverPosition({ anchor: chip(150, 10), width: 56, height: 30, placement: "above", ...screen });
  assert.equal(flip.placement, "below");
  const bottom = popoverPosition({ anchor: chip(150, 760), width: 200, height: 100, ...screen });
  assert.equal(bottom.placement, "above");
});

test("오른쪽 배치는 칩 오른쪽 테두리에 붙고 위쪽을 맞춘다", () => {
  const p = popoverPosition({ anchor: chip(40), width: 190, height: 120, placement: "right", ...screen });
  assert.equal(p.placement, "right");
  assert.equal(p.left, 100); // 칩 오른쪽 끝(40 + 60)
  assert.equal(p.top, 300);
});

test("오른쪽에 자리가 없으면 왼쪽, 둘 다 없으면 아래", () => {
  const left = popoverPosition({ anchor: chip(240), width: 190, height: 120, placement: "right", ...screen });
  assert.equal(left.placement, "left");
  assert.equal(left.left, 240 - 190);
  const below = popoverPosition({ anchor: chip(150), width: 340, height: 120, placement: "right", ...screen });
  assert.equal(below.placement, "below");
});

test("키보드가 올라오면 키보드 위로 피한다", () => {
  const p = popoverPosition({ anchor: chip(150, 400), width: 240, height: 160, keyboardTop: 500, ...screen });
  assert.equal(p.placement, "above");
  assert.ok(p.top + 160 <= 500 - POPOVER_MARGIN);
  const tight = popoverPosition({ anchor: chip(150, 100), width: 240, height: 300, keyboardTop: 400, ...screen });
  assert.ok(tight.top + 300 <= 400 - POPOVER_MARGIN); // 어느 쪽도 안 맞으면 키보드 위로 끌어올린다
  const side = popoverPosition({ anchor: chip(40, 450), width: 190, height: 200, placement: "right", keyboardTop: 500, ...screen });
  assert.ok(side.top + 200 <= 500 - POPOVER_MARGIN); // 옆에 붙어도 키보드 위로 끌어올린다
});
