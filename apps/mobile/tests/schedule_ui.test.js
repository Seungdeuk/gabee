// 일정 메인 브리핑 이름·다가오는 일정 제한의 순수 로직 시험: node --import ./tests/register-alias.mjs --test tests/schedule_ui.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { briefingLabels } from "../src/features/schedule/briefing.js";
import { pageUpcoming } from "../src/features/schedule/upcoming.js";

test("오늘을 고르면 오늘 / 내일 · 날짜", () => {
  assert.deepEqual(briefingLabels("2026-10-28", "2026-10-28"), ["오늘", "내일 · 10월 29일"]);
});

test("내일을 고르면 내일 · 날짜 / 다음 날 · 날짜", () => {
  assert.deepEqual(briefingLabels("2026-10-29", "2026-10-28"), ["내일 · 10월 29일", "다음 날 · 10월 30일"]);
});

test("그 밖의 날은 날짜로, 어제를 고르면 다음 날이 오늘이다", () => {
  assert.deepEqual(briefingLabels("2026-11-03", "2026-10-28"), ["11월 3일", "다음 날 · 11월 4일"]);
  assert.deepEqual(briefingLabels("2026-10-27", "2026-10-28"), ["어제 · 10월 27일", "오늘"]);
});

test("월말을 넘겨도 다음 날 계산이 맞다", () => {
  assert.deepEqual(briefingLabels("2026-10-31", "2026-10-28"), ["10월 31일", "다음 날 · 11월 1일"]);
});

const item = (id, date) => ({ id, date });
const TODAY = "2026-10-28";
const ids = (list) => list.map((x) => x.id);

test("다가오는 것: 5개 이하면 전부 보이고 남은 것은 없다", () => {
  const list = [item("a", "2026-10-29"), item("b", "2026-10-30")];
  assert.deepEqual(pageUpcoming(list, TODAY), { shown: list, remaining: 0 });
});

test("다가오는 것: 5번째와 같은 날짜의 일정은 5개를 넘어도 모두 보인다", () => {
  const list = [
    item("1", "2026-10-29"),
    item("2", "2026-10-29"),
    item("3", "2026-10-30"),
    item("4", "2026-10-30"),
    item("5", "2026-10-30"),
    item("6", "2026-10-30"),
    item("7", "2026-11-02"),
  ];
  const { shown, remaining } = pageUpcoming(list, TODAY);
  assert.deepEqual(ids(shown), ["1", "2", "3", "4", "5", "6"]);
  assert.equal(remaining, 1);
});

test("다가오는 것: 더보기를 누를 때마다 5개씩(같은 날짜는 모두) 늘어난다", () => {
  const list = Array.from({ length: 12 }, (_, i) => item(String(i + 1), `2026-11-${String(i + 1).padStart(2, "0")}`));
  assert.deepEqual(ids(pageUpcoming(list, TODAY, 1).shown), ["1", "2", "3", "4", "5"]);
  assert.equal(pageUpcoming(list, TODAY, 1).remaining, 7);
  assert.deepEqual(ids(pageUpcoming(list, TODAY, 2).shown), ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]);
  assert.equal(pageUpcoming(list, TODAY, 2).remaining, 2);
  assert.deepEqual(pageUpcoming(list, TODAY, 3), { shown: list, remaining: 0 });
});

test("다가오는 것: 앞으로 30일을 넘는 일정은 더보기에도 없다", () => {
  const list = [
    item("1", "2026-10-29"),
    item("2", "2026-10-30"),
    item("3", "2026-11-01"),
    item("4", "2026-11-05"),
    item("5", "2026-11-10"),
    item("6", "2026-11-20"),
    item("7", "2026-11-27"), // 오늘+30일 = 11-27, 포함
    item("8", "2026-11-28"), // 31일째, 제외
  ];
  const { shown, remaining } = pageUpcoming(list, TODAY);
  assert.deepEqual(ids(shown), ["1", "2", "3", "4", "5"]);
  assert.equal(remaining, 2);
  assert.deepEqual(ids(pageUpcoming(list, TODAY, 2).shown), ["1", "2", "3", "4", "5", "6", "7"]);
});

test("같이 요청처럼 날짜가 안쪽에 있는 항목도 dateOf 로 계산한다", () => {
  const list = [1, 2, 3, 4, 5, 6].map((n) => ({ request: { id: String(n), date: `2026-10-${28 + (n > 3 ? 2 : n)}` } }));
  const { shown, remaining } = pageUpcoming(list, TODAY, 1, { dateOf: (m) => m.request.date });
  assert.equal(shown.length + remaining, 6);
});
