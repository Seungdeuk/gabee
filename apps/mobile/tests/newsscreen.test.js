// 우리 가족 뉴스 화면의 판정(순수 함수) 시험: "한 주의 기록"을 처음에 펼칠지, 기록 요약 한 줄. npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { recordDefaultOpen, recordSummary } from "../src/features/more/news/newsView.js";

const WEEK = "2026-11-02";
const ready = { status: "ready", week_start: WEEK, items: [{ text: "기사" }] };
const open = (over) => recordDefaultOpen({ phase: "loaded", news: ready, weekStart: WEEK, docsStatus: "ok", ...over });

test("뉴스가 읽힌 주는 기록을 접어 둔다", () => {
  assert.equal(open({}), false);
});

test("뉴스가 없는 주(아직 안 만듦·이른 주·재료 없음·실패·만드는 중)는 기록을 펼친다", () => {
  for (const status of ["not_generated", "too_early", "empty", "failed", "pending"]) {
    assert.equal(open({ news: { status, week_start: WEEK } }), true, status);
  }
});

test("읽힘 상태여도 기사가 하나도 없으면 기록을 펼친다(0개 안내와 함께)", () => {
  assert.equal(open({ news: { status: "ready", week_start: WEEK, items: [] } }), true);
  assert.equal(open({ news: { status: "ready", week_start: WEEK } }), true);
});

test("뉴스를 불러오지 못했으면 기록을 펼친다", () => {
  assert.equal(open({ phase: "error", news: null }), true);
});

test("뉴스를 받는 중이거나 아직 다른 주의 응답이면 정하지 않고 접어 둔다(열렸다 닫히며 튀지 않게)", () => {
  assert.equal(open({ phase: "loading" }), false);
  assert.equal(open({ phase: "loading", news: null }), false);
  assert.equal(open({ news: { status: "ready", week_start: "2026-10-26" } }), false); // 이전 주 응답
  assert.equal(open({ news: { status: "failed", week_start: "2026-10-26" } }), false);
});

test("문서를 불러오지 못했으면 뉴스가 있어도 기록을 펼쳐서 알림을 보이게 한다", () => {
  assert.equal(open({ docsStatus: "failed" }), true);
  assert.equal(open({ docsStatus: "failed", phase: "loading" }), true);
});

test("기록 요약: 문서를 불러오지 못했으면 그렇다고 말한다(조용히 빼지 않는다)", () => {
  const base = { sharedCount: 3, todoDone: 0, docCount: null };
  assert.equal(recordSummary(base, "failed"), "공유 일정 3건 · 완료한 할 일 0건 · 문서를 불러오지 못했어요");
  assert.equal(recordSummary(base, "loading"), "공유 일정 3건 · 완료한 할 일 0건");
  assert.equal(recordSummary({ ...base, docCount: 2 }, "ok"), "공유 일정 3건 · 완료한 할 일 0건 · 공유 문서 2건");
});
