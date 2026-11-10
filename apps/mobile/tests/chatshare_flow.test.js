// 공유 보내기 화면 흐름(시트 → 확인창 → 전송)의 상태 전이 순수 함수: 한 번에 창 하나, 고르면 대기 뒤에만 확인창, 취소하면 시트 재오픈, 늦은 목록 응답 무시, 확인 중복 누름: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { SHARE_FLOW_IDLE, shareFlowReducer as reduce } from "../src/features/family-chat/shareFlow.js";

const months = [{ key: "m:2026-11", ref: "2026-11", title: "2026년 11월", line: "", badge: "정산" }];
const events = [{ key: "e:1", ref: "1", title: "치과", line: "11월 12일 (목) · 오후 3:00", badge: "약속" }];
const run = (state, ...actions) => actions.reduce(reduce, state);
const opened = run(SHARE_FLOW_IDLE, { type: "open", kind: "event", token: 1 }, { type: "loaded", token: 1, items: events });

test("open(정산): 시트가 열리고 항목이 바로 채워지며 확인 상태는 비어 있다", () => {
  const s = reduce(SHARE_FLOW_IDLE, { type: "open", kind: "settlement", token: 1, items: months });
  assert.deepEqual({ k: s.kind, st: s.status, items: s.items, sheet: s.sheetOpen, confirm: s.confirmOpen, pending: s.pending }, { k: "settlement", st: "ready", items: months, sheet: true, confirm: false, pending: null });
});

test("open(일정): 불러오는 중으로 열리고, 같은 요청의 결과만 반영한다(오류도 같다)", () => {
  const loading = reduce(SHARE_FLOW_IDLE, { type: "open", kind: "event", token: 7 });
  assert.equal(loading.status, "loading");
  assert.equal(loading.sheetOpen, true);
  assert.equal(reduce(loading, { type: "loaded", token: 6, items: events }), loading); // 이전 요청의 응답은 버린다
  assert.equal(reduce(loading, { type: "failed", token: 6, error: "x" }), loading);
  const ready = reduce(loading, { type: "loaded", token: 7, items: events });
  assert.deepEqual([ready.status, ready.items], ["ready", events]);
  const failed = reduce(loading, { type: "failed", token: 7, error: "불러오지 못했어요" });
  assert.deepEqual([failed.status, failed.error, failed.items], ["error", "불러오지 못했어요", []]);
});

test("close 뒤에 늦게 온 목록 응답은 버리고, 닫아도 종류·항목은 남겨 닫히는 동안 제목이 비지 않는다", () => {
  const loading = reduce(SHARE_FLOW_IDLE, { type: "open", kind: "event", token: 3 });
  const closed = reduce(loading, { type: "close" });
  assert.equal(closed.sheetOpen, false);
  assert.equal(closed.kind, "event");
  assert.equal(reduce(closed, { type: "loaded", token: 3, items: events }), closed);
  const readyClosed = reduce(opened, { type: "close" });
  assert.deepEqual([readyClosed.kind, readyClosed.items], ["event", events]);
});

test("open 은 이전 선택(pending)과 확인창 상태를 비우고 새로 시작한다", () => {
  const confirming = run(opened, { type: "pick", item: events[0] }, { type: "showConfirm" });
  assert.equal(confirming.confirmOpen, true);
  const again = reduce(confirming, { type: "open", kind: "settlement", token: 2, items: months });
  assert.deepEqual([again.pending, again.confirmOpen, again.sheetOpen, again.items], [null, false, true, months]);
});

test("pick: 시트를 닫고 항목을 기억할 뿐 확인창은 아직 열지 않는다(대기 뒤 showConfirm 에서만 연다)", () => {
  const picked = reduce(opened, { type: "pick", item: events[0] });
  assert.deepEqual([picked.sheetOpen, picked.confirmOpen, picked.pending], [false, false, events[0]]);
  assert.equal(reduce(picked, { type: "showConfirm" }).confirmOpen, true);
  assert.equal(reduce(opened, { type: "showConfirm" }), opened); // 고른 항목이 없거나 시트가 열려 있으면 확인창을 열지 않는다
});

test("cancelPending: 확인창만 닫고 목록·선택은 남기며, 대기 뒤 reopenSheet 로 시트가 다시 열린다", () => {
  const confirming = run(opened, { type: "pick", item: events[0] }, { type: "showConfirm" });
  const canceled = reduce(confirming, { type: "cancelPending" });
  assert.deepEqual([canceled.confirmOpen, canceled.sheetOpen, canceled.items, canceled.pending], [false, false, events, events[0]]);
  const back = reduce(canceled, { type: "reopenSheet" });
  assert.deepEqual([back.sheetOpen, back.confirmOpen, back.items], [true, false, events]);
});

test("cancelPending·reopenSheet 는 상태가 맞지 않으면 아무것도 하지 않는다(가드)", () => {
  assert.equal(reduce(opened, { type: "cancelPending" }), opened); // 확인창이 열려 있지 않다
  const confirming = run(opened, { type: "pick", item: events[0] }, { type: "showConfirm" });
  assert.equal(reduce(confirming, { type: "reopenSheet" }), confirming); // 확인창이 떠 있는 동안 시트를 열지 않는다
  assert.equal(reduce(SHARE_FLOW_IDLE, { type: "reopenSheet" }), SHARE_FLOW_IDLE); // 종류가 없으면 열지 않는다
});

test("confirm: 확인창을 닫고, 두 번째 confirm 은 무시된다(중복 누름)", () => {
  const confirming = run(opened, { type: "pick", item: events[0] }, { type: "showConfirm" });
  const sent = reduce(confirming, { type: "confirm" });
  assert.equal(sent.confirmOpen, false);
  assert.equal(sent.pending, events[0]); // 닫히는 동안 확인창 문구가 비지 않게 남긴다
  assert.equal(reduce(sent, { type: "confirm" }), sent);
});

test("어떤 순서로 눌러도 시트와 확인창이 동시에 열리지 않는다", () => {
  const types = ["pick", "showConfirm", "cancelPending", "reopenSheet", "close", "confirm"];
  let seen = 0;
  const walk = (state, depth) => {
    assert.equal(state.sheetOpen && state.confirmOpen, false);
    seen += 1;
    if (depth === 0) return;
    for (const type of types) walk(reduce(state, type === "pick" ? { type, item: events[0] } : { type }), depth - 1);
    walk(reduce(state, { type: "open", kind: "event", token: depth }), depth - 1);
  };
  walk(opened, 4);
  assert.ok(seen > 1000);
});
