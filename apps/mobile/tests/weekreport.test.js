// 마이 > AI 리포트 주간 집계 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MAX_WEEKS_BACK,
  buildReport,
  canGoBack,
  canGoForward,
  formatTime,
  todayKst,
  weekRange,
} from "../src/features/more/report/weekReport.js";

// 2026-11-03 12:00 KST (화요일)
const NOW = Date.UTC(2026, 10, 3, 3, 0);
const TODAY = "2026-11-03";

const ev = (over) => ({
  id: 1,
  title: "일정",
  kind: 1,
  start_date: "2026-11-05",
  start_time: "16:00:00",
  end_time: null,
  checked: false,
  shared: true,
  ...over,
});
const doc = (over) => ({
  id: 1,
  title: "문서",
  sensitivity: "normal",
  created_at: "2026-11-03T03:00:00Z",
  ...over,
});
const report = (events, docs, offset = 0) =>
  buildReport({ events, docs, range: weekRange(NOW, offset), today: todayKst(NOW) });

test("todayKst: UTC 와 날짜가 다른 시각도 KST 로 계산한다", () => {
  assert.equal(todayKst(NOW), TODAY);
  assert.equal(todayKst(Date.UTC(2026, 10, 2, 15, 0)), "2026-11-03"); // 00:00 KST
  assert.equal(todayKst(Date.UTC(2026, 10, 2, 14, 59)), "2026-11-02"); // 23:59 KST
});

test("weekRange: 이번 주는 월~일, 월이 걸치지 않으면 짧은 라벨", () => {
  const r = weekRange(NOW, 0);
  assert.deepEqual(r, {
    start: "2026-11-02",
    end: "2026-11-08",
    label: "11월 2일 ~ 8일",
    title: "이번 주",
    offset: 0,
    isCurrent: true,
  });
});

test("weekRange: 월 경계(월요일 00:00 KST, 일요일 23:59 KST)", () => {
  const mon = Date.UTC(2026, 10, 1, 15, 0); // 11-02 00:00 KST
  assert.equal(weekRange(mon).start, "2026-11-02");
  const sunBefore = Date.UTC(2026, 10, 1, 14, 59); // 11-01 23:59 KST (일)
  assert.equal(weekRange(sunBefore).start, "2026-10-26");
  assert.equal(weekRange(sunBefore).end, "2026-11-01");
  const sunEnd = Date.UTC(2026, 10, 8, 14, 59); // 11-08 23:59 KST
  assert.equal(weekRange(sunEnd).end, "2026-11-08");
});

test("weekRange: 월이 걸치는 라벨과 지난주·N주 전 제목", () => {
  const last = weekRange(NOW, -1);
  assert.equal(last.start, "2026-10-26");
  assert.equal(last.end, "2026-11-01");
  assert.equal(last.label, "10월 26일 ~ 11월 1일");
  assert.equal(last.title, "지난주");
  assert.equal(last.isCurrent, false);
  const far = weekRange(NOW, -8);
  assert.equal(far.start, "2026-09-07");
  assert.equal(far.title, "8주 전");
  assert.equal(weekRange(NOW, -2).title, "2주 전");
});

test("canGoBack / canGoForward", () => {
  assert.equal(MAX_WEEKS_BACK, 8);
  assert.equal(canGoBack(0), true);
  assert.equal(canGoBack(-7), true);
  assert.equal(canGoBack(-8), false);
  assert.equal(canGoForward(0), false);
  assert.equal(canGoForward(-1), true);
});

test("formatTime: 종일과 12시간제", () => {
  assert.equal(formatTime(null, null), "종일");
  assert.equal(formatTime("00:00:00", "23:59:00"), "종일");
  assert.equal(formatTime("16:00:00", null), "오후 4:00");
  assert.equal(formatTime("09:30:00", null), "오전 9:30");
  assert.equal(formatTime("12:00:00", null), "오후 12:00");
  assert.equal(formatTime("00:30:00", null), "오전 12:30");
});

test("공유 아닌 일정·주 밖 일정·시작일 없는 줄은 제외한다", () => {
  const r = report(
    [
      ev({ id: 1 }),
      ev({ id: 2, shared: false }),
      ev({ id: 3, start_date: "2026-11-09" }),
      ev({ id: 4, start_date: "2026-11-01" }),
      ev({ id: 5, start_date: null }),
      ev({ id: 6, kind: 2, shared: false }),
    ],
    [],
  );
  assert.equal(r.sharedCount, 1);
  assert.equal(r.todoTotal, 0);
  assert.deepEqual(
    r.list.map((i) => i.id),
    [1],
  );
});

test("할 일은 kind 2 공유만 세고 완료 개수를 센다", () => {
  const r = report(
    [
      ev({ id: 1, kind: 2, checked: true }),
      ev({ id: 2, kind: 2, checked: false }),
      ev({ id: 3, kind: 2, checked: true, start_date: "2026-11-02" }),
      ev({ id: 4, kind: 2, checked: true, shared: false }),
    ],
    [],
  );
  assert.equal(r.todoTotal, 3);
  assert.equal(r.todoDone, 2);
  assert.equal(r.sharedCount, 0);
  assert.equal(r.state, "events_empty");
});

test("문서: 민감 제외, created_at KST 경계", () => {
  const docs = [
    doc({ id: 1 }),
    doc({ id: 2, sensitivity: "sensitive" }),
    doc({ id: 3, created_at: "2026-11-01T15:00:00Z" }), // 11-02 00:00 KST 포함
    doc({ id: 4, created_at: "2026-11-01T14:59:59Z" }), // 11-01 23:59 KST 제외
    doc({ id: 5, created_at: "2026-11-08T14:59:59Z" }), // 11-08 23:59 KST 포함
    doc({ id: 6, created_at: "2026-11-08T15:00:00Z" }), // 11-09 00:00 KST 제외
  ];
  const r = report([ev()], docs);
  assert.equal(r.docCount, 3);
  assert.equal(r.docsFailed, false);
});

test("이번 주 목록은 오늘 이전을 빼고 최대 3건, 날짜·시간 순", () => {
  const events = [
    ev({ id: 1, start_date: "2026-11-02", title: "지난 일정" }),
    ev({ id: 2, start_date: "2026-11-07", start_time: "10:00:00" }),
    ev({ id: 3, start_date: "2026-11-05", start_time: "18:00:00" }),
    ev({ id: 4, start_date: "2026-11-05", start_time: null }),
    ev({ id: 5, start_date: "2026-11-03", start_time: "09:00:00" }),
  ];
  const r = report(events, []);
  assert.equal(r.listTitle, "이번 주 남은 공유 일정");
  assert.equal(r.sharedCount, 5);
  assert.equal(r.listTotal, 4);
  assert.deepEqual(
    r.list.map((i) => i.id),
    [5, 4, 3],
  );
  assert.equal(r.list[0].weekday, "화");
  assert.equal(r.list[0].day, 3);
  assert.equal(r.list[0].meta, "오전 9:00 · 가족 공유");
  assert.equal(r.list[1].timeText, "종일");
});

test("지난 주 목록은 전부 포함하고 최대 5건", () => {
  const events = [26, 27, 28, 29, 30, 31].map((d) =>
    ev({ id: d, start_date: `2026-10-${d}`, start_time: "10:00:00" }),
  );
  const r = report(events, [], -1);
  assert.equal(r.listTitle, "그 주의 공유 일정");
  assert.equal(r.listTotal, 6);
  assert.equal(r.list.length, 5);
  assert.equal(r.list[0].date, "2026-10-26");
});

test("state: all_empty / events_empty / ok", () => {
  assert.equal(report([], []).state, "all_empty");
  assert.equal(report([], [doc()]).state, "events_empty");
  assert.equal(report([], null).state, "events_empty");
  assert.equal(report([ev({ kind: 2 })], []).state, "events_empty");
  assert.equal(report([ev()], []).state, "ok");
});

test("docs 가 null 이면 docCount null, 문서 건수 없이 확인 불가 문장", () => {
  const r = report([ev()], null);
  assert.equal(r.docCount, null);
  assert.equal(r.docsFailed, true);
  assert.ok(r.line.includes("공유한 문서는 지금 확인할 수 없어요."));
  assert.ok(!/문서가 \d|문서는 \d/.test(r.line));
});

test("line: 이번 주 문구", () => {
  assert.equal(
    report([], []).line,
    "이번 주는 아직 가족이 공유한 기록이 없어요. 일정이나 할 일을 등록하고 문서를 공유하면 여기에 모아 보여 드릴게요.",
  );
  const r = report(
    [ev({ id: 1 }), ev({ id: 2 }), ev({ id: 3, kind: 2, checked: true }), ev({ id: 4, kind: 2 })],
    [doc()],
  );
  assert.equal(
    r.line,
    "이번 주 공유 일정은 2건이에요. 할 일은 2건 중 1건 끝냈어요. 공유한 문서가 1건 있어요.",
  );
  assert.equal(
    report([ev({ kind: 2, checked: true })], []).line,
    "이번 주는 공유 일정이 없어요. 할 일 1건을 모두 끝냈어요.",
  );
});

test("line: 지난 주는 과거형, 주 이름 지난주/그 주", () => {
  assert.equal(report([], [], -1).line, "지난주에는 가족이 공유한 기록이 없었어요.");
  assert.equal(report([], [], -3).line, "그 주에는 가족이 공유한 기록이 없었어요.");
  const r = report(
    [ev({ start_date: "2026-10-28" }), ev({ id: 2, kind: 2, checked: true, start_date: "2026-10-29" })],
    [doc({ created_at: "2026-10-28T03:00:00Z" })],
    -1,
  );
  assert.equal(
    r.line,
    "지난주 공유 일정은 1건이었어요. 할 일 1건을 모두 끝냈어요. 공유한 문서는 1건이었어요.",
  );
  assert.equal(
    report([ev({ kind: 2, start_date: "2026-10-28" })], [], -1).line,
    "지난주는 공유 일정이 없었어요. 할 일은 1건 중 0건 끝냈어요.",
  );
});

test("인사이트(이번 주): 남은 할 일 + 가장 가까운 일정", () => {
  const r = report(
    [ev({ id: 1, start_date: "2026-11-05", title: "병원" }), ev({ id: 2, kind: 2, checked: false })],
    [],
  );
  assert.deepEqual(r.insights, [
    { key: "todo_left", text: "이번 주 남은 할 일이 1건 있어요.", action: "schedule" },
    { key: "next_event", text: "가장 가까운 일정은 목요일 병원이에요." },
  ]);
});

test("인사이트(이번 주): 오늘·내일 문구, 할 일 모두 완료면 todo_left 없음", () => {
  const today = report([ev({ start_date: "2026-11-03", title: "회식" })], []);
  assert.deepEqual(today.insights, [{ key: "next_event", text: "오늘 회식 일정이 있어요." }]);
  const tomorrow = report([ev({ start_date: "2026-11-04", title: "학원" })], []);
  assert.equal(tomorrow.insights[0].text, "내일 학원 일정이 있어요.");
  const done = report([ev({ kind: 2, checked: true })], []);
  assert.deepEqual(done.insights, []);
});

test("인사이트(지난 주): 미완료 할 일, 모두 완료, 가장 바쁜 날(동률이면 빠른 날)", () => {
  const events = [
    ev({ id: 1, start_date: "2026-10-30" }),
    ev({ id: 2, start_date: "2026-10-30" }),
    ev({ id: 3, start_date: "2026-10-28" }),
    ev({ id: 4, start_date: "2026-10-28" }),
    ev({ id: 5, kind: 2, checked: true, start_date: "2026-10-27" }),
    ev({ id: 6, kind: 2, checked: false, start_date: "2026-10-27" }),
  ];
  const r = report(events, [], -1);
  assert.deepEqual(r.insights, [
    { key: "todo_left", text: "지난주 할 일 2건 중 1건은 아직 완료되지 않았어요.", action: "schedule" },
    { key: "busiest", text: "수요일에 공유 일정이 가장 많았어요(2건)." },
  ]);
  const done = report([ev({ kind: 2, checked: true, start_date: "2026-10-27" })], [], -2);
  assert.deepEqual(done.insights, []);
  const done2 = report([ev({ kind: 2, checked: true, start_date: "2026-10-27" })], [], -1);
  assert.deepEqual(done2.insights, [{ key: "todo_done", text: "지난주 할 일 1건을 모두 끝냈어요." }]);
});

test("인사이트는 최대 2개", () => {
  const events = [
    ev({ id: 1, start_date: "2026-10-28" }),
    ev({ id: 2, start_date: "2026-10-28" }),
    ev({ id: 3, kind: 2, start_date: "2026-10-28" }),
  ];
  assert.equal(report(events, [], -1).insights.length, 2);
});

test("일정은 있었지만 이번 주에 남은 것이 없으면 state 는 ok 이고 목록이 비어 있다", () => {
  const r = report([ev({ start_date: "2026-11-02" })], []);
  assert.equal(r.state, "ok");
  assert.equal(r.sharedCount, 1);
  assert.equal(r.list.length, 0);
  assert.equal(r.listTotal, 0);
});

test("문서 올린 시각: 마이크로초와 시간대 없는 값도 KST 날짜로 센다", () => {
  const range = weekRange(NOW, 0);
  const base = { events: [], range, today: TODAY };
  // 2026-11-01T15:30:00Z = 2026-11-02 00:30 KST(이번 주 월요일)
  assert.equal(buildReport({ ...base, docs: [doc({ created_at: "2026-11-01T15:30:00.123456Z" })] }).docCount, 1);
  assert.equal(buildReport({ ...base, docs: [doc({ created_at: "2026-11-01T15:30:00.123456" })] }).docCount, 1);
  // 2026-11-01T14:59:59Z = 2026-11-01 23:59 KST(지난 주 일요일)
  assert.equal(buildReport({ ...base, docs: [doc({ created_at: "2026-11-01T14:59:59.999999Z" })] }).docCount, 0);
});

test("start_date 가 없는 할 일은 세지 않는다", () => {
  const r = report([ev({ kind: 2, start_date: null })], []);
  assert.equal(r.todoTotal, 0);
});
