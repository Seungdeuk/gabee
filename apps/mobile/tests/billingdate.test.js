// 지출 입력의 날짜 도우미(일 수, 처음값, 맞추기, 빠른 선택, 직접 입력)를 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { clampDay, currentMonth, dayOptions, daysInMonth, defaultDay, expenseDate, parseDayInput, quickDays } from "../src/features/billing/format.js";

const at = (y, m, d) => new Date(y, m - 1, d, 12, 0, 0);

test("달의 일 수는 윤년을 반영한다", () => {
  assert.equal(daysInMonth("2026-02"), 28);
  assert.equal(daysInMonth("2028-02"), 29);
  assert.equal(daysInMonth("2026-04"), 30);
  assert.equal(daysInMonth("2026-12"), 31);
});

test("처음 날짜: 이번 달을 보면 오늘, 다른 달이면 1일", () => {
  const now = at(2026, 11, 11);
  assert.equal(defaultDay("2026-11", now), 11);
  assert.equal(defaultDay("2026-10", now), 1);
  assert.equal(defaultDay("2027-01", now), 1);
});

test("currentMonth 는 기준 시각을 받을 수 있고 인자가 없으면 지금이다", () => {
  assert.equal(currentMonth(at(2026, 3, 5)), "2026-03");
  assert.match(currentMonth(), /^\d{4}-\d{2}$/);
});

test("일은 1~말일로 맞추고 숫자가 아니면 1", () => {
  assert.equal(clampDay("2026-11", 31), 30);
  assert.equal(clampDay("2026-11", 0), 1);
  assert.equal(clampDay("2026-11", -5), 1);
  assert.equal(clampDay("2026-11", "7"), 7);
  assert.equal(clampDay("2026-11", "abc"), 1);
  assert.equal(clampDay("2026-11", 7.9), 7);
});

test("서버에 보낼 날짜는 YYYY-MM-DD 이고 없는 날(11월 31일)은 말일로 맞춘다", () => {
  assert.equal(expenseDate("2026-11", 5), "2026-11-05");
  assert.equal(expenseDate("2026-11", 30), "2026-11-30");
  assert.equal(expenseDate("2026-11", 31), "2026-11-30");
  assert.equal(expenseDate("2026-02", 31), "2026-02-28");
  assert.equal(expenseDate("2028-02", 31), "2028-02-29");
});

test("빠른 선택은 보고 있는 달 안의 오늘·어제만 준다", () => {
  const mid = at(2026, 11, 11);
  assert.deepEqual(quickDays("2026-11", mid), [
    { label: "오늘", day: 11 },
    { label: "어제", day: 10 },
  ]);
  // 달의 첫날이면 어제는 지난 달이라 뺀다
  assert.deepEqual(quickDays("2026-11", at(2026, 11, 1)), [{ label: "오늘", day: 1 }]);
  // 다른 달을 보고 있으면 없다
  assert.deepEqual(quickDays("2026-10", mid), []);
  // 달 경계(3월 1일, 평년)에서 어제는 2월 28일이라 3월에는 없다
  assert.deepEqual(quickDays("2026-03", at(2026, 3, 1)), [{ label: "오늘", day: 1 }]);
  assert.deepEqual(quickDays("2026-02", at(2026, 3, 1)), [{ label: "어제", day: 28 }]);
});

test("일 휠 선택지는 1일~말일이고 직접 입력은 범위 안일 때만 읽는다", () => {
  const opts = dayOptions("2026-04");
  assert.equal(opts.length, 30);
  assert.deepEqual(opts[0], { value: 1, label: "1일" });
  assert.deepEqual(opts[29], { value: 30, label: "30일" });
  assert.equal(parseDayInput("2026-04", "15"), 15);
  assert.equal(parseDayInput("2026-04", "15일"), 15);
  assert.equal(parseDayInput("2026-04", "31"), null);
  assert.equal(parseDayInput("2026-04", "0"), null);
  assert.equal(parseDayInput("2026-04", ""), null);
  assert.equal(parseDayInput("2026-04", "가"), null);
});
