// 대화 분석의 일정 후보: 날짜·시간이 빠진 후보를 칩과 시간 입력으로 채워 바로 등록할 수 있게 하는 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { canRegisterSchedule } from "../src/features/family-chat/messages.js";
import {
  completeScheduleCandidate,
  formatTimeInput,
  isTime,
  scheduleCandidateNeeds,
} from "../src/features/family-chat/scheduleCandidateUtils.js";

const NOW = new Date(2026, 10, 5, 9, 0); // 2026-11-05 09:00(기기 시간대)

test("formatTimeInput: 숫자만 남기고 두 자리 뒤에 콜론을 붙인다", () => {
  assert.equal(formatTimeInput("1930"), "19:30");
  assert.equal(formatTimeInput("19"), "19");
  assert.equal(formatTimeInput("193"), "19:3");
  assert.equal(formatTimeInput("ab12"), "12");
  assert.equal(formatTimeInput("123456"), "12:34");
  assert.equal(formatTimeInput("19:30"), "19:30");
  assert.equal(formatTimeInput(undefined), "");
});

test("isTime: 00:00~23:59 의 HH:MM 만 올바른 시간이다", () => {
  for (const ok of ["00:00", "09:30", "19:59", "23:59"]) assert.equal(isTime(ok), true, ok);
  for (const bad of ["24:00", "9:30", "19:60", "1930", "", null, "ab:cd"]) assert.equal(isTime(bad), false, String(bad));
});

test("scheduleCandidateNeeds: 비어 있는 날짜·시간만 입력이 필요하다", () => {
  assert.deepEqual(scheduleCandidateNeeds({ title: "병원", date: "2026-11-12", time: "10:30" }), { date: false, time: false });
  assert.deepEqual(scheduleCandidateNeeds({ title: "소풍", date: "2026-11-07", time: null }), { date: false, time: true });
  assert.deepEqual(scheduleCandidateNeeds({ title: "식사", date: null, time: null }), { date: true, time: true });
  assert.deepEqual(scheduleCandidateNeeds(null), { date: true, time: true });
});

test("completeScheduleCandidate: 빠진 시간을 입력으로 채우면 바로 등록할 수 있다", () => {
  const base = { title: "할머니 댁 방문", date: "2026-11-07", time: null, place: null };
  assert.equal(canRegisterSchedule(base), false);
  const done = completeScheduleCandidate(base, { timeText: "12:30" }, NOW);
  assert.equal(done.time, "12:30");
  assert.equal(done.date, "2026-11-07");
  assert.equal(canRegisterSchedule(done), true);
  assert.equal(base.time, null); // 원래 후보는 바꾸지 않는다
});

test("completeScheduleCandidate: 날짜 칩과 직접 입력으로 날짜를 채운다", () => {
  const base = { title: "가족 식사", date: null, time: null };
  const tomorrow = completeScheduleCandidate(base, { day: "tomorrow", timeText: "18:00" }, NOW);
  assert.deepEqual([tomorrow.date, tomorrow.time], ["2026-11-06", "18:00"]);
  const custom = completeScheduleCandidate(base, { day: "custom", customText: "2026-11-20", timeText: "07:05" }, NOW);
  assert.deepEqual([custom.date, custom.time], ["2026-11-20", "07:05"]);
  assert.equal(canRegisterSchedule(tomorrow) && canRegisterSchedule(custom), true);
});

test("completeScheduleCandidate: 올바르지 않거나 비어 있는 입력은 채우지 않아 등록할 수 없다", () => {
  const base = { title: "가족 식사", date: null, time: null };
  assert.equal(canRegisterSchedule(completeScheduleCandidate(base, {}, NOW)), false);
  assert.equal(canRegisterSchedule(completeScheduleCandidate(base, { day: "tomorrow", timeText: "9:00" }, NOW)), false); // 시간 형식 틀림
  assert.equal(canRegisterSchedule(completeScheduleCandidate(base, { timeText: "18:00" }, NOW)), false); // 날짜 없음
  assert.equal(completeScheduleCandidate(base, { day: "custom", customText: "2026-11-01", timeText: "18:00" }, NOW).date, null); // 지난 날짜
  assert.equal(completeScheduleCandidate(base, { day: "custom", customText: "2026-02-31", timeText: "18:00" }, NOW).date, null); // 없는 날짜
});

test("completeScheduleCandidate: 후보에 이미 있는 값은 입력으로 덮어쓰지 않는다", () => {
  const full = { title: "병원 예약", date: "2026-11-12", time: "10:30" };
  const out = completeScheduleCandidate(full, { day: "tomorrow", timeText: "18:00" }, NOW);
  assert.deepEqual([out.date, out.time], ["2026-11-12", "10:30"]);
});
