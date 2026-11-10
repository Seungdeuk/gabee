import assert from "node:assert/strict";
import test from "node:test";

import { draftDateOf, fromServerSuggestion, suggestionExtras } from "@/features/schedule/suggestion_convert";
import {
  SUGGESTIONS_DONE_TEXT,
  SUGGESTIONS_FILTERED_TEXT,
  SUGGESTIONS_NO_DATA_TEXT,
  SUGGESTIONS_PREPARING_TEXT,
  SUGGESTIONS_SPENT_EMPTY_TEXT,
  emptySlotView,
} from "@/features/schedule/suggestion_slot";

test("서버 제안은 화면 제안 모양으로 바뀐다(kind 1=약속, 2=할 일)", () => {
  assert.deepEqual(fromServerSuggestion({ id: "s1", title: "정기 검진", kind: 1, start_date: "2026-11-03", place: "내과" }), {
    id: "s1",
    name: "정기 검진",
    later: false,
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


test("서버가 나중에로 표시한 추천은 later 로 온다", () => {
  assert.equal(fromServerSuggestion({ id: "s1", title: "검진", kind: 1, start_date: "2026-11-03", later: true }).later, true);
  assert.equal(fromServerSuggestion({ id: "s2", title: "검진", kind: 1, start_date: "2026-11-03" }).later, false);
});

const loaded = (patch) => ({ loading: false, loaded: true, failed: false, state: "ok", canRefresh: true, ...patch });

test("추천 카드가 비면 서버 상태로 문구를 정한다: 데이터 없음 🌱 / 걸러짐 생각중 / 준비 중 ⏳ / 여기까지", () => {
  assert.deepEqual(emptySlotView(loaded({ state: "no_data" })), { kind: "message", text: SUGGESTIONS_NO_DATA_TEXT, refresh: true });
  assert.deepEqual(emptySlotView(loaded({ state: "filtered" })), { kind: "message", text: SUGGESTIONS_FILTERED_TEXT, refresh: true });
  assert.deepEqual(emptySlotView(loaded({ state: "preparing" })), { kind: "message", text: SUGGESTIONS_PREPARING_TEXT, refresh: true });
  assert.deepEqual(emptySlotView(loaded({ state: "spent_empty" })), { kind: "message", text: SUGGESTIONS_SPENT_EMPTY_TEXT, refresh: false });
  assert.notEqual(SUGGESTIONS_SPENT_EMPTY_TEXT, SUGGESTIONS_DONE_TEXT); // 추천을 못 받았는데 마무리 인사를 하지 않는다
  assert.deepEqual(emptySlotView(loaded({ state: "exhausted" })), { kind: "message", text: SUGGESTIONS_DONE_TEXT, refresh: false });
  assert.notEqual(SUGGESTIONS_NO_DATA_TEXT, SUGGESTIONS_FILTERED_TEXT);
  assert.equal(SUGGESTIONS_FILTERED_TEXT, "어울리는 일정을 생각중이에요…"); // 데이터가 있는데 "추천드릴 게 없다"고 하지 않는다
  assert.ok(!SUGGESTIONS_FILTERED_TEXT.includes("없어요"));
});

test("새로고침이 의미 없는 오류(AI 꺼짐 등)는 버튼을 숨기고, 서버에 못 간 실패는 준비 중 + 새로고침", () => {
  assert.equal(emptySlotView(loaded({ state: "preparing", canRefresh: false })).refresh, false);
  assert.deepEqual(emptySlotView(loaded({ failed: true, state: "ok" })), { kind: "message", text: SUGGESTIONS_PREPARING_TEXT, refresh: true });
});

test("불러오는 중이거나 아직 못 불러왔으면 loading", () => {
  assert.deepEqual(emptySlotView({ loading: true, loaded: false }), { kind: "loading" });
  assert.deepEqual(emptySlotView({ loading: false, loaded: false }), { kind: "loading" });
});
