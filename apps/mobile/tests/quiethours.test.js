// 방해금지 시간 직접 설정: 시각 파싱, 휠(시 00~23·분 00~59)·직접 입력, 시작=끝 방지, 켜기 기본값·유지, 화면 구성을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  QUIET_HOUR_OPTIONS,
  QUIET_MINUTE_OPTIONS,
  formatQuietSummary,
  isQuietClash,
  isQuietOn,
  parseQuietInput,
  parseTime,
  setQuietPart,
  toClockString,
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

test("withQuiet: default on, keeps existing times, normalizes to HH:MM, off clears", () => {
  const on = withQuiet(base, true);
  assert.deepEqual([on.quiet_start, on.quiet_end], ["22:00", "07:00"]);
  const custom = withQuiet({ ...base, quiet_start: "23:30:00", quiet_end: "06:00:00" }, true);
  assert.deepEqual([custom.quiet_start, custom.quiet_end], ["23:30", "06:00"]);
  const off = withQuiet(custom, false);
  assert.deepEqual([off.quiet_start, off.quiet_end], [null, null]);
  assert.equal(isQuietOn(off), false);
});

test("option lists: hours 00~23 (24), minutes 00~59 (60), two digits", () => {
  assert.equal(QUIET_HOUR_OPTIONS.length, 24);
  assert.deepEqual([QUIET_HOUR_OPTIONS[0], QUIET_HOUR_OPTIONS[23]], [{ value: 0, label: "00" }, { value: 23, label: "23" }]);
  assert.equal(QUIET_MINUTE_OPTIONS.length, 60);
  assert.deepEqual([QUIET_MINUTE_OPTIONS[0], QUIET_MINUTE_OPTIONS[7], QUIET_MINUTE_OPTIONS[59]], [
    { value: 0, label: "00" },
    { value: 7, label: "07" },
    { value: 59, label: "59" },
  ]);
});

test("parseQuietInput: one or two digits within range, else null", () => {
  assert.equal(parseQuietInput("7", "hour"), 7);
  assert.equal(parseQuietInput("07", "hour"), 7);
  assert.equal(parseQuietInput("23", "hour"), 23);
  assert.equal(parseQuietInput("0", "hour"), 0);
  assert.equal(parseQuietInput(" 5 ", "minute"), 5);
  assert.equal(parseQuietInput("59", "minute"), 59);
  for (const bad of ["24", "-1", "", "ab", "1a", "123", "1.5", null, undefined]) assert.equal(parseQuietInput(bad, "hour"), null, String(bad));
  assert.equal(parseQuietInput("60", "minute"), null);
  assert.equal(parseQuietInput("", "minute"), null);
});

test("setQuietPart changes one part (hour 0~23, minute 0~59) and sends HH:MM", () => {
  const s = { ...base, quiet_start: "22:00:00", quiet_end: "07:00" };
  const a = setQuietPart(s, "quiet_start", "hour", 23);
  assert.deepEqual([a.quiet_start, a.quiet_end], ["23:00", "07:00"]);
  const b = setQuietPart(s, "quiet_end", "minute", 37);
  assert.deepEqual([b.quiet_start, b.quiet_end], ["22:00", "07:37"]);
  assert.equal(s.quiet_start, "22:00:00"); // 입력은 바꾸지 않는다
  assert.equal(setQuietPart(s, "quiet_end", "hour", 0).quiet_end, "00:00");
  assert.equal(setQuietPart(s, "quiet_end", "minute", 59).quiet_end, "07:59");
});

test("setQuietPart rejects invalid values", () => {
  const s = { ...base, quiet_start: "22:00", quiet_end: "07:00" };
  for (const v of [-1, 24, 1.5, "5", NaN]) assert.equal(setQuietPart(s, "quiet_start", "hour", v), s);
  for (const v of [-1, 60, 2.5, "10"]) assert.equal(setQuietPart(s, "quiet_start", "minute", v), s);
  assert.equal(setQuietPart(s, "quiet_start", "second", 1), s);
});

test("setQuietPart keeps the previous value when start would equal end (wheel and typed input paths)", () => {
  const s = { ...base, quiet_start: "22:00", quiet_end: "07:00" };
  assert.equal(setQuietPart(s, "quiet_start", "hour", 7), s);
  assert.equal(isQuietClash(s, "quiet_start", "hour", 7), true);
  assert.equal(isQuietClash(s, "quiet_start", "hour", 8), false);
  assert.equal(isQuietClash(s, "quiet_end", "hour", 22), true);
  const t = { ...base, quiet_start: "07:05", quiet_end: "07:00" };
  assert.equal(setQuietPart(t, "quiet_start", "minute", 0), t);
  assert.equal(isQuietClash(t, "quiet_start", "minute", 0), true);
  // 직접 입력 문자열을 파싱한 값도 같은 규칙을 지난다
  assert.equal(setQuietPart(t, "quiet_start", "minute", parseQuietInput("0", "minute")), t);
  assert.equal(setQuietPart(t, "quiet_start", "minute", parseQuietInput("9", "minute")).quiet_start, "07:09");
});

test("setQuietPart does nothing when quiet is off", () => {
  assert.equal(setQuietPart(base, "quiet_start", "hour", 1), base);
});

test("formatQuietSummary uses 24h notation and 다음 날 only across midnight", () => {
  assert.equal(formatQuietSummary({ quiet_start: "22:00:00", quiet_end: "07:00:00" }), "22:00 ~ 다음 날 07:00에는 푸시를 보내지 않아요");
  assert.equal(formatQuietSummary({ quiet_start: "01:00", quiet_end: "05:30" }), "01:00 ~ 05:30에는 푸시를 보내지 않아요");
});

test("PushSettingsScreen shows one line with four wheels only when quiet is on, no AM/PM", () => {
  const src = readFileSync(new URL("../src/features/notifications/screens/PushSettingsScreen.js", import.meta.url), "utf8");
  assert.match(src, /isQuietOn\(settings\) \? \(/);
  assert.equal((src.match(/<WheelPicker\b/g) ?? []).length, 4);
  for (const label of ["시작 시", "시작 분", "끝 시", "끝 분"]) assert.ok(src.includes(`label="${label}"`), label);
  assert.ok(src.includes("setQuietPart"));
  assert.ok(src.includes("시작과 끝 시간이 같을 수 없어요"));
  assert.doesNotMatch(src, /오전|오후|MERIDIEM|Dropdown|toTwelveHour/);
  assert.match(src, /flexWrap: "nowrap"/);
});
