// 같이(부탁) 서버 변환 시험: node --import ./tests/register-alias.mjs --test tests/schedule_together.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { buildFamily } from "../src/features/schedule/members.js";
import { toRequest, toRequestBody } from "../src/features/schedule/together_convert.js";

const family = buildFamily({
  my_id: "u-me",
  members: [
    { id: "u-me", name: "민수", family_relation: "son" },
    { id: "u-mom", name: "영희", family_relation: "mom" },
    { id: "u-aunt", name: "이모", family_relation: "other", family_relation_detail: "이모" },
  ],
});

const out = {
  id: "r1",
  from_id: "u-mom",
  title: "장보기",
  start_date: "2026-11-01",
  start_time: "10:00:00",
  end_time: "11:30:00",
  place: "마트",
  memo: "",
  created_at: "2026-10-27T00:00:00Z",
  canceled: false,
  recipients: [
    { user_id: "u-me", status: "accepted" },
    { user_id: "u-aunt", status: "waiting" },
  ],
  my_event_id: "e1",
};

test("RequestOut: 앱 id·답·시간 변환, waiting 은 키 없음", () => {
  const r = toRequest(out, family);
  assert.equal(r.fromId, "mom");
  assert.deepEqual(r.toIds, ["me", "u-aunt"]);
  assert.deepEqual(r.replies, { me: "accepted" });
  assert.equal(r.startTime, "10:00");
  assert.equal(r.endTime, "11:30");
  assert.equal(r.allDay, false);
  assert.deepEqual(r.whoIds, []);
  assert.equal(r.itemId, "e1");
  assert.equal(r.cancelled, false);
});

test("RequestOut: 00:00~23:59 는 종일, 시간 없음은 null, 취소·거절", () => {
  const all = toRequest({ ...out, start_time: "00:00:00", end_time: "23:59:00", my_event_id: null, canceled: true }, family);
  assert.equal(all.allDay, true);
  assert.equal(all.startTime, null);
  assert.equal(all.cancelled, true);
  assert.equal(all.itemId, null);
  const none = toRequest({ ...out, start_time: null, end_time: null, recipients: [{ user_id: "u-me", status: "declined" }] }, family);
  assert.equal(none.startTime, null);
  assert.deepEqual(none.replies, { me: "declined" });
});

test("보내기 본문: 종일·시간 없음·끝 없음·받는 사람 사용자 id", () => {
  const base = { title: "t", date: "2026-11-01", place: "", memo: "", toIds: ["mom", "u-aunt", "nobody"] };
  const allDay = toRequestBody({ ...base, allDay: true, startTime: null, endTime: null }, family);
  assert.equal(allDay.start_time, "00:00");
  assert.equal(allDay.end_time, "23:59");
  assert.deepEqual(allDay.to_ids, ["u-mom", "u-aunt"]);
  const none = toRequestBody({ ...base, allDay: false, startTime: null, endTime: "12:00" }, family);
  assert.equal(none.start_time, null);
  assert.equal(none.end_time, null);
  const noEnd = toRequestBody({ ...base, allDay: false, startTime: "09:00", endTime: null }, family);
  assert.equal(noEnd.start_time, "09:00");
  assert.equal(noEnd.end_time, null);
});
