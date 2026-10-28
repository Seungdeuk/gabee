// 일정 서버 연동의 순수 변환 시험: node --import ./tests/register-alias.mjs --test tests/schedule_api.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { toBody, toItem, toPatchBody } from "../src/features/schedule/api.js";
import { applyFilter, involvedIds, isShared, whoChips } from "../src/features/schedule/filter.js";
import { buildFamily } from "../src/features/schedule/members.js";

const group = {
  my_id: "u-me",
  members: [
    { id: "u-me", name: "민수", family_relation: "son" },
    { id: "u-mom", name: "영희", display_name: "영희", family_relation: "mom" },
    { id: "u-dad", name: "철수", family_relation: "dad" },
    { id: "u-aunt", name: "이모", family_relation: "other", family_relation_detail: "이모" },
  ],
};
const family = buildFamily(group);

test("가족: 나는 me, 엄마·아빠는 mom·dad, 나머지는 사용자 id", () => {
  assert.deepEqual(
    family.members.map((m) => [m.id, m.name]),
    [
      ["me", "나"],
      ["mom", "엄마"],
      ["dad", "아빠"],
      ["u-aunt", "이모"],
    ],
  );
  assert.equal(family.toApp("u-mom"), "mom");
  assert.equal(family.toUser("dad"), "u-dad");
  assert.equal(family.toUser("me"), "u-me");
  assert.equal(family.toApp("nobody"), null);
});

test("가족: 엄마 관계가 둘이면 먼저 나온 사람만 mom", () => {
  const f = buildFamily({
    my_id: "a",
    members: [
      { id: "a", name: "나" },
      { id: "b", name: "새엄마", family_relation: "mom" },
      { id: "c", name: "엄마2", family_relation: "mom" },
    ],
  });
  assert.equal(f.toApp("b"), "mom");
  assert.equal(f.toApp("c"), "c");
});

const event = {
  id: "e1",
  title: "가족 점심",
  starts_at: "2030-01-05T03:00:00Z",
  kind: 1,
  shared: true,
  shared_ids: ["u-mom", "u-dad", "ghost"],
  place: "본가",
  start_date: "2030-01-05",
  start_time: "12:00:00",
  end_time: "14:00:00",
  memo: "과일 사 가기",
  note: "과일 사 가기",
  checked: true,
  created_by: "u-mom",
  origin_id: "e0",
  topic_id: "t1",
};

test("이름은 별명(getGroupWithNicknames 가 입힌 nickname) → 관계 → 표시 이름 순", () => {
  const named = buildFamily({
    ...group,
    members: group.members.map((m) => (m.id === "u-dad" ? { ...m, nickname: "아버지" } : m)),
  });
  assert.deepEqual(
    named.members.map((m) => [m.id, m.name]),
    [
      ["me", "나"],
      ["mom", "엄마"],
      ["dad", "아버지"],
      ["u-aunt", "이모"],
    ],
  );
});

test("서버 일정 → 화면 항목", () => {
  assert.deepEqual(toItem(event, family), {
    id: "e1",
    kind: "appointment",
    title: "가족 점심",
    date: "2030-01-05",
    startTime: "12:00",
    endTime: "14:00",
    allDay: false,
    place: "본가",
    memo: "과일 사 가기",
    topicId: "t1",
    sharedWith: [],
    shared: true,
    sharedIds: ["mom", "dad"], // 모르는 사람은 뺀다
    createdBy: "mom",
    checked: true,
  });
});

test("00:00~23:59 는 종일, 시간이 없으면 시간 없음, 시작만 있으면 끝 미정", () => {
  const allDay = toItem({ ...event, kind: 2, start_time: "00:00:00", end_time: "23:59:00" }, family);
  assert.equal(allDay.allDay, true);
  assert.equal(allDay.kind, "todo");
  assert.equal(allDay.startTime, null);
  const none = toItem({ ...event, start_time: null, end_time: null }, family);
  assert.deepEqual([none.allDay, none.startTime, none.endTime], [false, null, null]);
  const open = toItem({ ...event, end_time: null }, family);
  assert.deepEqual([open.startTime, open.endTime], ["12:00", null]);
});

const item = {
  kind: "todo",
  title: "세탁물",
  date: "2030-02-01",
  startTime: "18:00",
  endTime: null,
  allDay: false,
  place: "",
  memo: "",
  topicId: null,
  sharedWith: ["mom"],
};

test("화면 항목 → 등록 본문: 종일은 00:00~23:59, 공유는 사용자 id", () => {
  assert.deepEqual(toBody(item, family, { create: true }), {
    title: "세탁물",
    kind: 2,
    start_date: "2030-02-01",
    start_time: "18:00",
    end_time: null,
    place: "",
    memo: "",
    topic_id: null,
    share_with: ["u-mom"],
  });
  const allDay = toBody({ ...item, allDay: true, startTime: null }, family);
  assert.deepEqual([allDay.start_time, allDay.end_time], ["00:00", "23:59"]);
  assert.equal("share_with" in allDay, false);
  const noTime = toBody({ ...item, startTime: null, endTime: "19:00" }, family);
  assert.deepEqual([noTime.start_time, noTime.end_time], [null, null]); // 시작이 없으면 끝도 없다
});

test("수정 본문은 바꾼 값만, 시간은 날짜·시간을 함께 보낸다", () => {
  const current = { ...item, id: "x", checked: false };
  assert.deepEqual(toPatchBody({ title: "새 제목" }, current, family), { title: "새 제목" });
  assert.deepEqual(toPatchBody({ topicId: "t9" }, current, family), {
    topic_id: "t9",
  });
  assert.deepEqual(toPatchBody({ startTime: null }, current, family), {
    start_date: "2030-02-01",
    start_time: null,
    end_time: null,
  });
  assert.deepEqual(toPatchBody({ allDay: true, startTime: null, endTime: null }, current, family), {
    start_date: "2030-02-01",
    start_time: "00:00",
    end_time: "23:59",
  });
});

test("수정 본문은 공유 대상을 바꿨을 때만 share_with 로 전체를 보낸다", () => {
  const current = { ...item, id: "x", checked: false };
  assert.deepEqual(toPatchBody({ sharedWith: ["mom", "dad"] }, current, family), {
    share_with: ["u-mom", "u-dad"],
  });
  assert.deepEqual(toPatchBody({ sharedWith: [] }, current, family), { share_with: [] }); // 모두 뺄 때
  assert.equal("share_with" in toPatchBody({ title: "새 제목" }, current, family), false);
});

test("공동 여부와 대상 필터: 나는 나 혼자 일정, 공동은 공동 일정, 구성원은 그 사람과 얽힌 공동 일정", () => {
  const alone = { ...item, id: "a", shared: false, sharedIds: [], sharedWith: [], createdBy: "me" };
  const withMom = { ...item, id: "b", shared: true, sharedIds: ["mom"], sharedWith: ["mom"], createdBy: "me" };
  const fromDad = { ...item, id: "c", shared: true, sharedIds: ["dad", "mom"], sharedWith: [], createdBy: "dad" };
  const all = [alone, withMom, fromDad];
  const ids = (list) => list.map((x) => x.id);
  assert.equal(isShared(alone), false);
  assert.equal(isShared(withMom), true);
  assert.deepEqual(ids(applyFilter(all, { whoIds: [], topicIds: [] })), ["a", "b", "c"]); // 안 켜면 전체
  assert.deepEqual(ids(applyFilter(all, { whoIds: ["me"], topicIds: [] })), ["a"]);
  assert.deepEqual(ids(applyFilter(all, { whoIds: ["shared"], topicIds: [] })), ["b", "c"]);
  assert.deepEqual(ids(applyFilter(all, { whoIds: ["mom"], topicIds: [] })), ["b", "c"]);
  assert.deepEqual(ids(applyFilter(all, { whoIds: ["dad"], topicIds: [] })), ["c"]);
  assert.deepEqual(ids(applyFilter(all, { whoIds: ["me", "dad"], topicIds: [] })), ["a", "c"]); // 같은 줄은 또는
});

test("서버 값이 없는 mock 일정은 공유 대상이 있거나 남이 만들었으면 공동", () => {
  assert.equal(isShared({ ...item, sharedWith: [], createdBy: "me" }), false);
  assert.equal(isShared({ ...item, sharedWith: ["mom"], createdBy: "me" }), true);
  assert.equal(isShared({ ...item, sharedWith: [], createdBy: "mom" }), true);
  assert.deepEqual(involvedIds({ ...item, sharedWith: ["mom"], createdBy: "dad" }).sort(), ["dad", "mom"]);
});

test("대상 칩: 나 · 공동 · 가족 구성원 순(부모님 칩은 없다)", () => {
  assert.deepEqual(
    whoChips(family.members).map((c) => [c.id, c.label]),
    [
      ["me", "나"],
      ["shared", "공동"],
      ["mom", "엄마"],
      ["dad", "아빠"],
      ["u-aunt", "이모"],
    ],
  );
});
