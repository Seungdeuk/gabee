// 보낸 부탁의 브리핑 합치기·수락 현황·받는 사람 바꾸기 시트 규칙 시험: node --import ./tests/register-alias.mjs --test tests/schedule_request_view.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { cancelMessage, sheetGuide, splitChips } from "../src/features/schedule/recipients_edit.js";
import { acceptSummary, briefingRequests, mergeBriefing } from "../src/features/schedule/request_view.js";
import { toRequest } from "../src/features/schedule/together_convert.js";
import { buildFamily } from "../src/features/schedule/members.js";

// model.js 의 compareItems 와 같은 규칙(약속 먼저, 종일 → 시간 있음 → 시간 없음, 시작 시각순). model.js 는 테마를 불러와 node 에서 못 읽는다.
function compareItems(a, b) {
  if (a.kind !== b.kind) return a.kind === "appointment" ? -1 : 1;
  const rank = (x) => (x.allDay ? 0 : x.startTime ? 1 : 2);
  if (a.kind === "appointment" && rank(a) !== rank(b)) return rank(a) - rank(b);
  return (a.startTime ?? "").localeCompare(b.startTime ?? "");
}
const TODAY = "2026-10-29";
const req = (id, over = {}) => ({
  id,
  fromId: "me",
  toIds: ["mom", "dad", "bro"],
  title: id,
  date: TODAY,
  startTime: null,
  endTime: null,
  allDay: false,
  replies: {},
  cancelled: false,
  ...over,
});
const appt = (id, startTime, over = {}) => ({ id, kind: "appointment", allDay: false, startTime, checked: false, ...over });
const todo = (id, startTime = null) => ({ id, kind: "todo", allDay: false, startTime, checked: false });
const ids = (entries) => entries.map((e) => (e.type === "item" ? e.item.id : e.request.id));

test("브리핑 부탁: 내가 보낸 것, 취소·지난 날짜·다른 날은 뺀다", () => {
  const list = [
    req("ok"),
    req("others", { fromId: "mom" }),
    req("canceled", { cancelled: true }),
    req("other-day", { date: "2026-10-30" }),
    req("past", { date: "2026-10-28" }),
  ];
  assert.deepEqual(briefingRequests(list, "me", TODAY, TODAY).map((r) => r.id), ["ok"]);
  assert.deepEqual(briefingRequests(list, "me", "2026-10-30", TODAY).map((r) => r.id), ["other-day"]);
  assert.deepEqual(briefingRequests(list, "me", "2026-10-28", TODAY), []);
});

test("합치기: 부탁은 약속 사이에 시간순, 할 일은 뒤, 같은 시각이면 일정이 먼저", () => {
  const items = [appt("a9", "09:00"), appt("a18", "18:30"), todo("t17", "17:00"), appt("a15", "15:00")];
  const merged = mergeBriefing(items, [req("r15", { startTime: "15:00" }), req("rall", { allDay: true })], compareItems);
  assert.deepEqual(ids(merged), ["rall", "a9", "a15", "r15", "a18", "t17"]);
  assert.deepEqual(ids(mergeBriefing([], [req("r")], compareItems)), ["r"]);
  assert.deepEqual(ids(mergeBriefing([appt("none", null)], [req("r", { startTime: "10:00" })], compareItems)), ["r", "none"]);
});

test("수락 현황: 기다려요 / 수락 n/m / 전원 수락", () => {
  assert.deepEqual(acceptSummary(req("a")), { label: "기다려요", full: false });
  assert.deepEqual(acceptSummary(req("a", { replies: { mom: "declined" } })), { label: "기다려요", full: false });
  assert.deepEqual(acceptSummary(req("a", { replies: { mom: "accepted" } })), { label: "수락 1/3", full: false });
  assert.deepEqual(acceptSummary(req("a", { replies: { mom: "accepted", dad: "accepted", bro: "accepted" } })), { label: "수락 3/3", full: true });
});

const members = [{ id: "mom" }, { id: "dad" }, { id: "bro" }, { id: "sis" }];
const current = ["mom", "dad", "bro"];
const replies = { mom: "accepted", dad: "declined" };

test("시트 칩: 위 줄은 수락한 사람, 아래 줄은 나머지", () => {
  const { accepted, others } = splitChips(members, current, replies);
  assert.deepEqual(accepted.map((m) => m.id), ["mom"]);
  assert.deepEqual(others.map((m) => m.id), ["dad", "bro", "sis"]);
});

test("시트 안내: 수락한 분 제외 / 안 한 분만 제외 / 빈 선택 / 변화 없음", () => {
  assert.deepEqual(sheetGuide(current, replies, ["dad", "bro"]), { message: "수락한 분을 제외하면 그 일정도 같이 사라져요", canSave: true });
  assert.deepEqual(sheetGuide(current, replies, ["mom", "dad"]), { message: "제외한 분은 이 부탁을 더 볼 수 없어요", canSave: true });
  assert.deepEqual(sheetGuide(current, replies, []), { message: "한 명 이상 골라 주세요. 모두 빼려면 부탁을 취소해 주세요", canSave: false });
  assert.deepEqual(sheetGuide(current, replies, ["bro", "dad", "mom"]), { message: null, canSave: false });
  assert.deepEqual(sheetGuide(current, replies, [...current, "sis"]), { message: null, canSave: true });
});

test("취소 팝업 본문: 수락한 사람이 있을 때만 일정 삭제 줄", () => {
  assert.equal(cancelMessage(false), "받는 분께는 알림이 가지 않아요.");
  assert.equal(cancelMessage(true), "취소하면 수락하신 분이 만든 일정도 같이 사라져요.\n받는 분께는 알림이 가지 않아요.");
});

test("부탁 응답 변환: edited_at 이 있으면 editedAt, 없으면 null", () => {
  const family = buildFamily({ my_id: "u-me", members: [{ id: "u-me", name: "민수", family_relation: "son" }] });
  const out = { id: "r", from_id: "u-me", title: "t", start_date: TODAY, start_time: null, end_time: null, recipients: [] };
  assert.equal(toRequest(out, family).editedAt, null);
  assert.equal(toRequest({ ...out, edited_at: "2026-10-29T01:00:00Z" }, family).editedAt, "2026-10-29T01:00:00Z");
});
