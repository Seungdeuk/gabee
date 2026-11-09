// 방해금지 시간 직접 설정: 시각 파싱, 시/분 선택, 시작=끝 방지, 켜기 기본값·유지, 화면 구성을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  QUIET_HOUR_OPTIONS,
  QUIET_MINUTE_OPTIONS,
  formatQuietSummary,
  isQuietClash,
  isQuietOn,
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

test("setQuietPart changes one part and sends HH:MM", () => {
  const s = { ...base, quiet_start: "22:00:00", quiet_end: "07:00" };
  const a = setQuietPart(s, "quiet_start", "hour", 23);
  assert.deepEqual([a.quiet_start, a.quiet_end], ["23:00", "07:00"]);
  const b = setQuietPart(s, "quiet_end", "minute", 35);
  assert.deepEqual([b.quiet_start, b.quiet_end], ["22:00", "07:35"]);
  assert.equal(s.quiet_start, "22:00:00"); // 입력은 바꾸지 않는다
  assert.equal(setQuietPart(s, "quiet_start", "hour", 0).quiet_start, "00:00");
  assert.equal(setQuietPart(s, "quiet_end", "hour", 23).quiet_end, "23:00");
});

test("setQuietPart rejects out-of-range values and minutes that are not multiples of 5", () => {
  const s = { ...base, quiet_start: "22:00", quiet_end: "07:00" };
  assert.equal(setQuietPart(s, "quiet_start", "hour", 24), s);
  assert.equal(setQuietPart(s, "quiet_start", "hour", -1), s);
  assert.equal(setQuietPart(s, "quiet_start", "hour", 1.5), s);
  assert.equal(setQuietPart(s, "quiet_start", "minute", 7), s);
  assert.equal(setQuietPart(s, "quiet_start", "minute", 60), s);
  assert.equal(setQuietPart(s, "quiet_start", "minute", "10"), s);
});

test("setQuietPart keeps the previous value when start would equal end", () => {
  const s = { ...base, quiet_start: "22:00", quiet_end: "07:00" };
  assert.equal(setQuietPart(s, "quiet_start", "hour", 7), s);
  assert.equal(isQuietClash(s, "quiet_start", "hour", 7), true);
  assert.equal(isQuietClash(s, "quiet_start", "hour", 8), false);
  assert.equal(isQuietClash(s, "quiet_end", "hour", 22), true);
  const t = { ...base, quiet_start: "07:05", quiet_end: "07:00" };
  assert.equal(setQuietPart(t, "quiet_start", "minute", 0), t);
  assert.equal(isQuietClash(t, "quiet_start", "minute", 0), true);
});

test("setQuietPart does nothing when quiet is off", () => {
  assert.equal(setQuietPart(base, "quiet_start", "hour", 1), base);
});

test("option lists: hours 00~23, minutes 00,05..55 as two digits", () => {
  assert.equal(QUIET_HOUR_OPTIONS.length, 24);
  assert.deepEqual([QUIET_HOUR_OPTIONS[0], QUIET_HOUR_OPTIONS[23]], [{ value: 0, label: "00" }, { value: 23, label: "23" }]);
  assert.equal(QUIET_MINUTE_OPTIONS.length, 12);
  assert.deepEqual(
    QUIET_MINUTE_OPTIONS.map((o) => o.label),
    ["00", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55"],
  );
});

test("formatQuietSummary reads from the current settings", () => {
  assert.equal(formatQuietSummary({ quiet_start: "22:00:00", quiet_end: "07:00:00" }), "22:00 ~ 다음 날 07:00에는 푸시를 보내지 않아요");
  assert.equal(formatQuietSummary({ quiet_start: "01:00", quiet_end: "05:30" }), "01:00 ~ 05:30에는 푸시를 보내지 않아요");
});

test("PushSettingsScreen shows one time line with four dropdowns only when quiet is on", () => {
  const src = readFileSync(new URL("../src/features/notifications/screens/PushSettingsScreen.js", import.meta.url), "utf8");
  assert.match(src, /isQuietOn\(settings\) \? \(/);
  assert.equal((src.match(/<Dropdown\b/g) ?? []).length, 4);
  for (const label of ["시작 시", "시작 분", "끝 시", "끝 분"]) assert.ok(src.includes(label), label);
  assert.ok(src.includes("setQuietPart"));
  assert.ok(src.includes("시작과 끝 시간이 같을 수 없어요"));
  assert.ok(!src.includes("stepQuietTime"));
  assert.match(src, /flexWrap: "nowrap"/);
});
