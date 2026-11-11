// 데일리 체크 줄 메뉴(수정·삭제, 길게 누르기) 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_menu.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { ROW_MENU, ROW_MENU_HOLD_MS, rowMenuAction, rowMenuTop } from "../src/features/schedule/daily/logic.js";

test("메뉴는 수정, 삭제 두 개, 삭제는 빨간 글자(danger)", () => {
  assert.deepEqual(ROW_MENU.map((m) => m.label), ["수정", "삭제"]);
  assert.equal(ROW_MENU.find((m) => m.key === "delete").danger, true);
  assert.equal(ROW_MENU.find((m) => m.key === "edit").danger, undefined);
});

test("메뉴 키 → 동작: 수정은 수정 화면, 삭제는 삭제 확인", () => {
  assert.equal(rowMenuAction("edit"), "edit");
  assert.equal(rowMenuAction("delete"), "delete");
  assert.equal(rowMenuAction("nope"), null);
});

test("메뉴 아이콘: 수정은 연필, 삭제는 휴지통", () => {
  assert.equal(ROW_MENU.find((x) => x.key === "edit").icon, "pencil");
  assert.equal(ROW_MENU.find((x) => x.key === "delete").icon, "trash");
});

test("길게 누르기 시간은 450ms 한 곳에서 정한다", () => {
  assert.equal(ROW_MENU_HOLD_MS, 450);
});

test("줄 메뉴 위치: 점 버튼 아래에 붙고, 맨 아래 줄은 위로 뒤집는다", () => {
  const stride = 82;
  const rowH = 72;
  const menuH = 96;
  // 첫 줄: 줄 top(0) + 44 → 점 버튼 바로 아래
  assert.equal(rowMenuTop(0, 3, stride, rowH, menuH), 44);
  // 가운데 줄: 줄 top(82) + 44
  assert.equal(rowMenuTop(1, 3, stride, rowH, menuH), 82 + 44);
  // 맨 아래 줄: 위로 뒤집기 (줄 top 164 + 72 - 96 + 8 = 148)
  assert.equal(rowMenuTop(2, 3, stride, rowH, menuH), 148);
  // 줄이 하나뿐이면 뒤집지 않는다
  assert.equal(rowMenuTop(0, 1, stride, rowH, menuH), 44);
});
