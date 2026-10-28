// 날짜 시트 달력 줄(월요일 시작) 시험: node --import ./tests/register-alias.mjs --test tests/schedule_month_grid.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { monthWeeks } from "../src/features/schedule/month_grid.js";

test("줄마다 7칸이고 월요일부터 시작한다", () => {
  for (const [y, m] of [[2026, 2], [2026, 8], [2026, 10], [2027, 1], [2024, 2]]) {
    const weeks = monthWeeks(y, m);
    assert.ok(weeks.length >= 4 && weeks.length <= 6);
    for (const week of weeks) assert.equal(week.length, 7);
    const first = weeks[0].find((key) => key !== null);
    assert.equal(weeks[0].indexOf(first), (new Date(`${first}T00:00:00`).getDay() + 6) % 7);
  }
});

test("그 달 날짜만 들어가고 앞뒤는 null 이다", () => {
  const weeks = monthWeeks(2026, 10); // 10월 1일은 목요일
  assert.deepEqual(weeks[0].slice(0, 4), [null, null, null, "2026-10-01"]);
  assert.equal(weeks.length, 5);
  assert.equal(weeks.flat().filter(Boolean).length, 31);
  assert.equal(weeks[4][5], "2026-10-31");
});

test("줄 수는 달마다 다르다(2월 4줄, 8월 6줄)", () => {
  assert.equal(monthWeeks(2027, 2).length, 4); // 2027년 2월은 월요일 시작, 28일
  assert.equal(monthWeeks(2026, 8).length, 6);
});
