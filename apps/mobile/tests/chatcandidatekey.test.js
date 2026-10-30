// AI 대화 분석 후보의 "등록함" 표시가 다시 분석해도 이어지게 하는 식별자·기록 시험: npm test
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { candidateKey, isCandidateDone, markCandidateDone, resetCandidateDone } from "../src/features/family-chat/candidateKey.js";

beforeEach(() => resetCandidateDone());

const schedule = { title: "병원 예약", date: "2026-11-02", time: "15:00", place: "서울병원" };

test("candidateKey: 같은 내용이면 필드 순서·재분석과 상관없이 같은 식별자, 내용이 다르면 다른 식별자", () => {
  const reordered = { place: "서울병원", time: "15:00", date: "2026-11-02", title: "병원 예약" };
  assert.equal(candidateKey("schedule", schedule), candidateKey("schedule", reordered));
  assert.notEqual(candidateKey("schedule", schedule), candidateKey("schedule", { ...schedule, time: "16:00" }));
  assert.notEqual(candidateKey("schedule", schedule), candidateKey("todo", schedule)); // 일정·할 일은 서로 섞이지 않는다
  assert.equal(typeof candidateKey("todo", null), "string");
});

test("candidateKey: 함수·객체 같은 값은 식별자에 넣지 않아 응답의 부가 객체가 달라도 같은 후보로 본다", () => {
  const a = { title: "장보기", extra: { n: 1 } };
  const b = { title: "장보기", extra: { n: 2 } };
  assert.equal(candidateKey("todo", a), candidateKey("todo", b));
});

test("markCandidateDone/isCandidateDone: 등록한 후보는 같은 내용으로 다시 분석돼도 등록한 것으로 보이고, 다른 후보는 그대로 활성", () => {
  const key = candidateKey("schedule", schedule);
  assert.equal(isCandidateDone(key), false);
  markCandidateDone(key);
  const reAnalyzed = { ...schedule }; // 다시 분석하면 같은 내용의 새 객체가 온다
  assert.equal(isCandidateDone(candidateKey("schedule", reAnalyzed)), true);
  assert.equal(isCandidateDone(candidateKey("schedule", { ...schedule, title: "치과" })), false);
  resetCandidateDone();
  assert.equal(isCandidateDone(key), false);
});
