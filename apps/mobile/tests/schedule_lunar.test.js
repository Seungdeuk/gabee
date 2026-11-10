// 양력 <-> 음력 변환 시험: node --import ./tests/register-alias.mjs --test tests/schedule_lunar.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { firstDayLabel, lunarToSolar, solarToLunar } from "../src/features/schedule/lunar.js";

test("양력에서 음력으로: 2026 설날은 음력 1월 1일", () => {
  assert.deepEqual(solarToLunar("2026-02-17"), { year: 2026, month: 1, day: 1, leap: false });
  assert.deepEqual(solarToLunar("2026-09-25"), { year: 2026, month: 8, day: 15, leap: false }); // 추석
});

test("음력에서 양력으로: 설날과 추석", () => {
  assert.equal(lunarToSolar(2026, 1, 1), "2026-02-17");
  assert.equal(lunarToSolar(2026, 8, 15), "2026-09-25");
});

test("없는 음력 날짜는 null 이다(그 달에 없는 31일, 13월)", () => {
  assert.equal(lunarToSolar(2026, 1, 31), null);
  assert.equal(lunarToSolar(2026, 13, 1), null);
});

test("지원 범위 밖 날짜는 null 이다", () => {
  assert.equal(solarToLunar("0999-01-01"), null);
  assert.equal(lunarToSolar(2060, 1, 1), null);
});

test("달력 칸 글: 음력 1일만 나온다", () => {
  assert.equal(firstDayLabel("2026-02-17"), "1.1");
  assert.equal(firstDayLabel("2026-02-18"), null);
  assert.equal(firstDayLabel(lunarToSolar(2025, 6, 1, true)), "윤 6.1");
});

test("양력 -> 음력 -> 양력이 되돌아온다", () => {
  for (const key of ["2026-01-01", "2026-11-09", "2027-03-15", "2028-07-04", "2030-12-31"]) {
    const l = solarToLunar(key);
    assert.equal(lunarToSolar(l.year, l.month, l.day, l.leap), key);
  }
});
