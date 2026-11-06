import assert from "node:assert/strict";
import test from "node:test";

import { describePermission, describeLastSent } from "../src/features/location/diagnostics.js";
import { statusLine } from "../src/features/location/status.js";
import { calendarWeek, weekDates, weekTitle } from "../src/features/location/timelineView.js";
import { describePause, lastPauseDate, previewPause } from "../src/features/location/travel.js";
import { localPauseState, trackingMode } from "../src/features/location/background.js";

const TODAY = "2026-11-06"; // 금요일

test("weekDates: 일요일에 시작하는 7일, 이전 주로 넘길 수 있다", () => {
  assert.deepEqual(weekDates(TODAY, 0), ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"]);
  assert.equal(weekDates(TODAY, 1)[0], "2026-10-25");
  assert.equal(weekDates("2026-11-01", 0)[0], "2026-11-01"); // 일요일은 그 주의 첫날
  assert.equal(weekDates("2026-11-07", 0)[6], "2026-11-07"); // 토요일은 마지막 날
});

test("calendarWeek: 오늘 표시, 미래는 future, 14일 밖은 expired", () => {
  const week = calendarWeek(TODAY, 0);
  assert.deepEqual(week.map((d) => d.weekday).join(""), "일월화수목금토");
  assert.equal(week.find((d) => d.isToday).date, TODAY);
  assert.equal(week.find((d) => d.date === "2026-11-07").state, "future");
  assert.ok(week.filter((d) => d.date <= TODAY).every((d) => d.state === "open"));
  const prev = calendarWeek(TODAY, 1);
  assert.ok(prev.every((d) => d.state === "open")); // 10/25~10/31 은 모두 14일 안(오늘 포함 14일은 10/24 부터)
  // 오늘이 월요일이면 지난 주 앞쪽 날들은 보관 기간 밖
  const mon = calendarWeek("2026-11-02", 1); // 10/25~10/31, 보관은 10/20 부터
  assert.ok(mon.every((d) => d.state === "open"));
  const late = calendarWeek("2026-11-14", 1); // 보관 11/1 부터, 지난 주 11/1 부터 11/7
  assert.ok(late.every((d) => d.state === "open"));
  const expired = calendarWeek("2026-11-20", 1); // 보관 11/7 부터, 지난 주 11/8~11/14 → 모두 open, 그 앞주
  assert.ok(expired.every((d) => d.state === "open"));
  const old = calendarWeek("2026-11-20", 2); // 11/1~11/7 중 11/7 만 open
  assert.deepEqual(old.map((d) => d.state), ["expired", "expired", "expired", "expired", "expired", "expired", "open"]);
});

test("weekTitle", () => {
  assert.equal(weekTitle(calendarWeek(TODAY, 0)), "11/1 ~ 11/7");
  assert.equal(weekTitle(calendarWeek(TODAY, 1)), "10/25 ~ 10/31");
});

test("lastPauseDate / previewPause: 오늘을 1일째로 센다", () => {
  assert.equal(lastPauseDate(TODAY, 1), "2026-11-06");
  assert.equal(lastPauseDate(TODAY, 3), "2026-11-08");
  assert.deepEqual(previewPause(TODAY, 3), { lastDate: "2026-11-08", untilText: "11/8까지", resumeText: "11/9 0시에 다시 공유해요" });
  assert.equal(previewPause("2026-12-30", 3).untilText, "1/1까지"); // 연말을 넘어도 맞다
});

test("describePause: 종료 시각(마지막 날 다음 날 0시, KST)에서 마지막 날과 D-day 를 구한다", () => {
  const until = "2026-11-08T15:00:00Z"; // = 11/9 00:00 KST, 마지막 날 11/8
  const now = Date.parse("2026-11-06T08:00:00Z"); // 11/6 17:00 KST
  const p = describePause(until, now);
  assert.equal(p.lastDate, "2026-11-08");
  assert.equal(p.ddayText, "D-2");
  assert.equal(p.untilText, "11/8까지");
  assert.equal(p.resumeText, "11/9 0시에 자동으로 다시 공유해요");
  assert.equal(describePause(until, Date.parse("2026-11-08T03:00:00Z")).ddayText, "D-day"); // 마지막 날 낮
  assert.equal(describePause(until, Date.parse("2026-11-08T14:59:00Z")).daysLeft, 0);
  assert.equal(describePause("2026-11-06T15:00:00+00:00", now).ddayText, "D-day"); // 1일: 오늘이 마지막 날
});

test("statusLine: 상태별 한 줄", () => {
  const base = { enabled: true, consent: true, paused: false, paused_until: null, background: false };
  assert.equal(statusLine(null).tone, "off");
  assert.equal(statusLine({ ...base, enabled: false }).tone, "off");
  assert.equal(statusLine({ ...base, consent: false }).text, "공유 꺼짐");
  assert.equal(statusLine(base).text, "공유 중 · 앱이 켜져 있을 때만");
  assert.equal(statusLine({ ...base, background: true }).text, "공유 중 · 앱을 꺼도 켜져 있어요");
  const paused = statusLine({ ...base, paused: true, paused_until: "2026-11-08T15:00:00Z" }, Date.parse("2026-11-06T08:00:00Z"));
  assert.deepEqual(paused, { tone: "pause", text: "여행 모드 · D-2 · 11/8까지" });
});

test("trackingMode: 여행 모드 중에는 끄지 않고 저전력 대기", () => {
  const base = { enabled: true, consent: true, background: true, paused: false };
  assert.equal(trackingMode(base), "normal");
  assert.equal(trackingMode({ ...base, paused: true }), "waiting");
  assert.equal(trackingMode({ ...base, background: false }), "off");
  assert.equal(trackingMode({ ...base, consent: false }), "off");
  assert.equal(trackingMode({ ...base, enabled: false }), "off");
  assert.equal(trackingMode(null), "off");
});

test("localPauseState: 기기에 저장한 종료 시각으로 보낼지 정한다", () => {
  const until = "2026-11-08T15:00:00Z";
  assert.equal(localPauseState(null), "none");
  assert.equal(localPauseState("망가진 값"), "none");
  assert.equal(localPauseState(until, Date.parse("2026-11-08T14:59:59Z")), "paused");
  assert.equal(localPauseState(until, Date.parse("2026-11-08T15:00:00Z")), "expired"); // 종료 시각 정각부터 다시 보낸다
  assert.equal(localPauseState(until, Date.parse("2026-11-09T01:00:00Z")), "expired");
});

test("describePermission / describeLastSent", () => {
  assert.deepEqual(describePermission("granted", "granted"), { ok: true, text: "항상 허용" });
  assert.equal(describePermission("granted", "denied").ok, false);
  assert.ok(describePermission("granted", "denied").text.includes("항상 허용"));
  assert.equal(describePermission("denied", "denied").ok, false);
  const now = Date.parse("2026-11-06T09:00:00Z");
  assert.equal(describeLastSent(null, now).ok, false);
  assert.deepEqual(describeLastSent("2026-11-06T08:55:00Z", now), { ok: true, text: "5분 전" });
  assert.equal(describeLastSent("2026-11-06T06:00:00Z", now).text, "3시간 전");
  assert.equal(describeLastSent("2026-11-04T06:00:00Z", now).text, "하루 넘게 전");
});
