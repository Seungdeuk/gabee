// 방해금지 시간 직접 설정: 시각 파싱·표기, 시/분 증감(순환), 시작=끝 방지, 켜기 기본값·유지, 화면 구성을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  formatQuietSummary,
  formatTimeKorean,
  isQuietOn,
  parseTime,
  stepQuietTime,
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

test("toClockString and formatTimeKorean", () => {
  assert.equal(toClockString({ hour: 7, minute: 5 }), "07:05");
  assert.equal(formatTimeKorean("22:00:00"), "오후 10:00");
  assert.equal(formatTimeKorean("07:00"), "오전 7:00");
  assert.equal(formatTimeKorean("00:30"), "오전 12:30");
  assert.equal(formatTimeKorean("12:00"), "오후 12:00");
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

test("stepQuietTime: hour wraps 23->0 and 0->23, one hour per step", () => {
  const s = { ...base, quiet_start: "23:00", quiet_end: "07:00" };
  assert.equal(stepQuietTime(s, "quiet_start", "hour", 1).quiet_start, "00:00");
  assert.equal(stepQuietTime({ ...s, quiet_start: "00:00" }, "quiet_start", "hour", -1).quiet_start, "23:00");
  assert.equal(stepQuietTime(s, "quiet_end", "hour", 1).quiet_end, "08:00");
});

test("stepQuietTime: minute steps by 5 and wraps 55->0 without touching the hour", () => {
  const s = { ...base, quiet_start: "22:55", quiet_end: "07:00:00" };
  assert.equal(stepQuietTime(s, "quiet_start", "minute", 1).quiet_start, "22:00");
  assert.equal(stepQuietTime({ ...s, quiet_start: "22:00" }, "quiet_start", "minute", -1).quiet_start, "22:55");
  assert.equal(stepQuietTime(s, "quiet_end", "minute", 1).quiet_end, "07:05");
  assert.equal(s.quiet_start, "22:55"); // 입력은 바꾸지 않는다
});

test("stepQuietTime never makes start equal end (skips one more step)", () => {
  const t = { ...base, quiet_start: "22:00", quiet_end: "23:00" };
  assert.equal(stepQuietTime(t, "quiet_start", "hour", 1).quiet_start, "00:00"); // 23:00 은 끝과 같아 건너뛴다
  const m = { ...base, quiet_start: "22:00", quiet_end: "22:05" };
  assert.equal(stepQuietTime(m, "quiet_start", "minute", 1).quiet_start, "22:10");
  assert.equal(stepQuietTime(m, "quiet_end", "minute", -1).quiet_end, "22:55"); // 분만 돌아 22:00 은 시작과 같아 건너뛰고 22:55 가 된다(시는 그대로)
});

test("stepQuietTime does nothing when quiet is off", () => {
  assert.deepEqual(stepQuietTime(base, "quiet_start", "hour", 1), base);
});

test("formatQuietSummary reads from the current settings", () => {
  assert.equal(formatQuietSummary({ quiet_start: "22:00:00", quiet_end: "07:00:00" }), "22:00 ~ 다음 날 07:00에는 푸시를 보내지 않아요");
  assert.equal(formatQuietSummary({ quiet_start: "01:00", quiet_end: "05:30" }), "01:00 ~ 05:30에는 푸시를 보내지 않아요");
});

test("PushSettingsScreen shows the time rows only when quiet is on, with accessibility labels", () => {
  const src = readFileSync(new URL("../src/features/notifications/screens/PushSettingsScreen.js", import.meta.url), "utf8");
  assert.match(src, /isQuietOn\(settings\) \? \(/);
  assert.match(src, /시작 시간/);
  assert.match(src, /끝 시간/);
  assert.ok(src.includes("label={`${label} 시`}")); // "시작 시간 시 줄이기" 처럼 이어진다
  assert.ok(src.includes("accessibilityLabel={`${label} 줄이기`}"));
  assert.ok(src.includes("accessibilityLabel={`${label} 늘리기`}"));
  assert.ok(src.includes("label={`${label} 분`}"));
  assert.match(src, /stepQuietTime/);
  assert.match(src, /minWidth: 44/);
  assert.match(src, /minHeight: 44/);
});
