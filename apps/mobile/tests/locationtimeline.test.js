import assert from "node:assert/strict";
import test from "node:test";

import { describeSegment, dayLabel, durationText, hhmm, shiftDay, todayKst } from "../src/features/location/timelineView.js";

test("todayKst: UTC 15시 이후는 한국 시간으로 다음 날", () => {
  assert.equal(todayKst(Date.parse("2026-11-09T14:59:00Z")), "2026-11-09");
  assert.equal(todayKst(Date.parse("2026-11-09T15:00:00Z")), "2026-11-10");
});

test("shiftDay: 월말·연말을 넘어도 맞다", () => {
  assert.equal(shiftDay("2026-11-01", -1), "2026-10-31");
  assert.equal(shiftDay("2026-12-31", 1), "2027-01-01");
  assert.equal(shiftDay("2026-11-09", 0), "2026-11-09");
});

test("dayLabel: 월·일·요일", () => {
  assert.equal(dayLabel("2026-11-09"), "11월 9일 (월)");
  assert.equal(dayLabel("2026-11-07"), "11월 7일 (토)");
});

test("hhmm: 시간대가 있는 시각을 한국 시간으로 보인다", () => {
  assert.equal(hhmm("2026-11-09T00:00:00Z"), "09:00");
  assert.equal(hhmm("2026-11-09T09:30:00+09:00"), "09:30");
});

test("durationText: 분·시간", () => {
  assert.equal(durationText("2026-11-09T09:00:00+09:00", "2026-11-09T09:25:00+09:00"), "25분");
  assert.equal(durationText("2026-11-09T09:00:00+09:00", "2026-11-09T10:00:00+09:00"), "1시간");
  assert.equal(durationText("2026-11-09T09:00:00+09:00", "2026-11-09T11:20:00+09:00"), "2시간 20분");
});

const at = (h, m = 0) => `2026-11-09T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00+09:00`;

test("describeSegment: 머묾·이동·기록 없음·구역 밖을 구분한다", () => {
  assert.deepEqual(describeSegment({ kind: "stay", start: at(9), end: at(11), place: "학교" }), {
    time: "09:00 ~ 11:00",
    title: "학교에서 머묾",
    sub: "2시간",
    tone: "normal",
  });
  assert.equal(describeSegment({ kind: "stay", start: at(9), end: at(10), place: null }).title, "이름 없는 곳에서 머묾");
  assert.equal(describeSegment({ kind: "move", start: at(11), end: at(11, 30), origin: "학교", place: "학원" }).title, "학교 → 학원");
  assert.equal(describeSegment({ kind: "move", start: at(11), end: at(11, 30) }).title, "이동 중");
  const gap = describeSegment({ kind: "no_record", start: at(12), end: at(13) });
  assert.equal(gap.tone, "muted");
  assert.ok(gap.sub.includes("앱이 꺼져 있었거나")); // 원인을 하나로 단정하지 않는다
  const out = describeSegment({ kind: "anomaly", start: at(1, 10), end: at(2, 30), place: null });
  assert.equal(out.tone, "warn");
  assert.ok(out.sub.startsWith("평소 활동 구역 밖"));
});
