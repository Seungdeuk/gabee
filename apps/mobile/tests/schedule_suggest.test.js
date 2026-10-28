import assert from "node:assert/strict";
import test from "node:test";

import { draftDateOf, fromServerSuggestion, suggestionExtras } from "@/features/schedule/suggestion_convert";

test("서버 제안은 화면 제안 모양으로 바뀐다(kind 1=약속, 2=할 일)", () => {
  assert.deepEqual(fromServerSuggestion({ id: "s1", title: "정기 검진", kind: 1, start_date: "2026-11-03", place: "내과" }), {
    id: "s1",
    name: "정기 검진",
    draft: { kind: "appointment", title: "정기 검진", date: "2026-11-03", place: "내과" },
  });
  const todo = fromServerSuggestion({ id: "s2", title: "관리비 납부", kind: 2, date: "2026-11-05" });
  assert.equal(todo.draft.kind, "todo");
  assert.equal(todo.draft.date, "2026-11-05");
  assert.equal(todo.draft.place, "");
});

test("날짜는 절대 날짜(draft.date)를 우선하고, 없으면 오늘 기준 daysFromToday", () => {
  assert.equal(draftDateOf({ date: "2026-12-01" }, "2026-10-27"), "2026-12-01");
  assert.equal(draftDateOf({ daysFromToday: 6 }, "2026-10-27"), "2026-11-02");
  assert.equal(draftDateOf({ daysFromToday: 10 }, "2026-12-25"), "2027-01-04");
});

test("등록 화면에 넘길 값: 서버 제안만 id 를 넘기고 장소는 있을 때만", () => {
  const server = fromServerSuggestion({ id: "s1", title: "검진", kind: 1, start_date: "2026-11-03", place: "내과" });
  assert.deepEqual(suggestionExtras(server), { place: "내과", suggestionId: "s1" });
  assert.deepEqual(suggestionExtras({ id: "passport", draft: { daysFromToday: 10 } }), {});
  assert.deepEqual(suggestionExtras({ draft: { place: "" } }), {});
});
