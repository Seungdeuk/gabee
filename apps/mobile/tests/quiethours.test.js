// 방해금지 시간 직접 설정: 시각 파싱, 오전/오후·1~12시·5분 선택, 시작=끝 방지, 켜기 기본값·유지, 화면 구성을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  QUIET_HOUR_OPTIONS,
  QUIET_MERIDIEM_OPTIONS,
  QUIET_MINUTE_OPTIONS,
  formatQuietSummary,
  fromTwelveHour,
  isQuietClash,
  isQuietOn,
  parseTime,
  setQuietPart,
  toClockString,
  toTwelveHour,
  withQuiet,
} from "../src/features/notifications/push.js";

const base = { enabled: true, preview_mode: "full", muted_kinds: [], quiet_start: null, quiet_end: null };

test("parseTime reads HH:MM and HH:MM:SS, rejects garbage", () => {
  assert.deepEqual(parseTime("22:00"), { hour: 22, minute: 0 });
  assert.deepEqual(parseTime("07:05:00"), { hour: 7, minute: 5 });
  assert.equal(parseTime(null), null);
  assert.equal(parseTime("25:00"), null);
  assert.equal(parseTime("abc"), null);
});

test("toClockString makes HH:MM", () => {
  assert.equal(toClockString({ hour: 7, minute: 5 }), "07:05");
});

test("24h <-> 12h conversion: 0, 1, 11, 12, 13, 23", () => {
  assert.deepEqual(toTwelveHour(0), { meridiem: "AM", hour12: 12 });
  assert.deepEqual(toTwelveHour(1), { meridiem: "AM", hour12: 1 });
  assert.deepEqual(toTwelveHour(11), { meridiem: "AM", hour12: 11 });
  assert.deepEqual(toTwelveHour(12), { meridiem: "PM", hour12: 12 });
  assert.deepEqual(toTwelveHour(13), { meridiem: "PM", hour12: 1 });
  assert.deepEqual(toTwelveHour(23), { meridiem: "PM", hour12: 11 });
  assert.equal(fromTwelveHour("AM", 12), 0);
  assert.equal(fromTwelveHour("PM", 12), 12);
  assert.equal(fromTwelveHour("AM", 1), 1);
  assert.equal(fromTwelveHour("PM", 1), 13);
  assert.equal(fromTwelveHour("PM", 11), 23);
});

test("every 24h value is representable and selectable in 12h form", () => {
  for (let h = 0; h < 24; h++) {
    const { meridiem, hour12 } = toTwelveHour(h);
    assert.equal(fromTwelveHour(meridiem, hour12), h);
    assert.ok(QUIET_HOUR_OPTIONS.some((o) => o.value === hour12));
    assert.ok(QUIET_MERIDIEM_OPTIONS.some((o) => o.value === meridiem));
  }
  const s = { ...base, quiet_start: "10:00", quiet_end: "07:00" };
  assert.equal(setQuietPart(setQuietPart(s, "quiet_start", "meridiem", "AM"), "quiet_start", "hour", 12).quiet_start, "00:00"); // 오전 12:00
  assert.equal(setQuietPart(s, "quiet_start", "hour", 12).quiet_start, "00:00"); // 오전 10 → 오전 12 = 00:00
  const t = { ...base, quiet_start: "22:00", quiet_end: "07:00" };
  assert.equal(setQuietPart(t, "quiet_start", "hour", 12).quiet_start, "12:00"); // 오후 12:00
});

test("withQuiet: default on, keeps existing times, normalizes to HH:MM, off clears", () => {
  const on = withQuiet(base, true);
  assert.deepEqual([on.quiet_start, on.quiet_end], ["22:00", "07:00"]);
  const custom = withQuiet({ ...base, quiet_start: "23:30:00", quiet_end: "06:00:00" }, true);
  assert.deepEqual([custom.quiet_start, custom.quiet_end], ["23:30", "06:00"]);
  const off = withQuiet(custom, false);
  assert.deepEqual([off.quiet_start, off.quiet_end], [null, null]);
  assert.equal(isQuietOn(off), false);
});

test("setQuietPart changes one part and sends HH:MM", () => {
  const s = { ...base, quiet_start: "22:00:00", quiet_end: "07:00" };
  const a = setQuietPart(s, "quiet_start", "hour", 11); // 오후 11
  assert.deepEqual([a.quiet_start, a.quiet_end], ["23:00", "07:00"]);
  const b = setQuietPart(s, "quiet_end", "minute", 35);
  assert.deepEqual([b.quiet_start, b.quiet_end], ["22:00", "07:35"]);
  assert.equal(s.quiet_start, "22:00:00"); // 입력은 바꾸지 않는다
  assert.equal(setQuietPart(s, "quiet_end", "hour", 12).quiet_end, "00:00"); // 오전 12 = 0시
});

test("setQuietPart meridiem only moves by 12 hours (10 PM -> AM is 10:00)", () => {
  const s = { ...base, quiet_start: "22:15", quiet_end: "07:00" };
  assert.equal(setQuietPart(s, "quiet_start", "meridiem", "AM").quiet_start, "10:15");
  assert.equal(setQuietPart(s, "quiet_end", "meridiem", "PM").quiet_end, "19:00");
  assert.equal(setQuietPart({ ...s, quiet_start: "00:30" }, "quiet_start", "meridiem", "PM").quiet_start, "12:30");
});

test("setQuietPart rejects invalid values (hour only 1~12, minute multiples of 5)", () => {
  const s = { ...base, quiet_start: "22:00", quiet_end: "07:00" };
  for (const v of [0, 13, -1, 1.5, "5"]) assert.equal(setQuietPart(s, "quiet_start", "hour", v), s);
  for (const v of [7, 60, -5, "10"]) assert.equal(setQuietPart(s, "quiet_start", "minute", v), s);
  assert.equal(setQuietPart(s, "quiet_start", "meridiem", "xx"), s);
  assert.equal(setQuietPart(s, "quiet_start", "second", 1), s);
});

test("setQuietPart keeps the previous value when start would equal end (meridiem included)", () => {
  const s = { ...base, quiet_start: "22:00", quiet_end: "23:00" };
  assert.equal(setQuietPart(s, "quiet_start", "hour", 11), s);
  assert.equal(isQuietClash(s, "quiet_start", "hour", 11), true);
  assert.equal(isQuietClash(s, "quiet_start", "hour", 9), false);
  const m = { ...base, quiet_start: "10:00", quiet_end: "22:00" };
  assert.equal(setQuietPart(m, "quiet_start", "meridiem", "PM"), m);
  assert.equal(isQuietClash(m, "quiet_start", "meridiem", "PM"), true);
  assert.equal(isQuietClash(m, "quiet_end", "meridiem", "AM"), true);
  const t = { ...base, quiet_start: "07:05", quiet_end: "07:00" };
  assert.equal(setQuietPart(t, "quiet_start", "minute", 0), t);
  assert.equal(isQuietClash(t, "quiet_start", "minute", 0), true);
});

test("setQuietPart does nothing when quiet is off", () => {
  assert.equal(setQuietPart(base, "quiet_start", "hour", 1), base);
});

test("option lists: AM/PM, hours 1~12 as 01~12, minutes 00,05..55", () => {
  assert.deepEqual(QUIET_MERIDIEM_OPTIONS, [{ value: "AM", label: "오전" }, { value: "PM", label: "오후" }]);
  assert.deepEqual(QUIET_HOUR_OPTIONS.map((o) => o.value), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  assert.deepEqual([QUIET_HOUR_OPTIONS[0].label, QUIET_HOUR_OPTIONS[11].label], ["01", "12"]);
  assert.deepEqual(
    QUIET_MINUTE_OPTIONS.map((o) => o.label),
    ["00", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55"],
  );
});

test("formatQuietSummary uses 12h notation and 다음 날 only across midnight", () => {
  assert.equal(formatQuietSummary({ quiet_start: "22:00:00", quiet_end: "07:00:00" }), "오후 10:00 ~ 다음 날 오전 07:00에는 푸시를 보내지 않아요");
  assert.equal(formatQuietSummary({ quiet_start: "01:00", quiet_end: "05:30" }), "오전 01:00 ~ 오전 05:30에는 푸시를 보내지 않아요");
  assert.equal(formatQuietSummary({ quiet_start: "00:00", quiet_end: "12:00" }), "오전 12:00 ~ 오후 12:00에는 푸시를 보내지 않아요");
});

test("PushSettingsScreen shows one line with six dropdowns only when quiet is on, no arrows", () => {
  const src = readFileSync(new URL("../src/features/notifications/screens/PushSettingsScreen.js", import.meta.url), "utf8");
  assert.match(src, /isQuietOn\(settings\) \? \(/);
  assert.equal((src.match(/<Dropdown\b/g) ?? []).length, 6);
  for (const label of ["시작 오전/오후", "시작 시", "시작 분", "끝 오전/오후", "끝 시", "끝 분"]) assert.ok(src.includes(`label="${label}"`), label);
  assert.ok(src.includes("setQuietPart"));
  assert.ok(src.includes("시작과 끝 시간이 같을 수 없어요"));
  assert.ok(!src.includes("stepQuietTime"));
  assert.doesNotMatch(src, /▾/);
  assert.match(src, /flexWrap: "nowrap"/);
});
