// PR10: 사용자 요청형 추억 생성의 앱 쪽 순수 로직 시험 — 상태 구분 표시, 오류 변환, 진행 확인 규칙, 가족 전환 시 상태 초기화·늦은 응답 폐기. npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  GENERATION_LABELS,
  GENERATION_POLL_MAX,
  generationError,
  generationReducer,
  generationView,
  initialGenerationState,
  shouldKeepPolling,
  shouldReloadCandidates,
} from "../src/features/family-memory/generation.js";

const gen = (state, extra = {}) => ({ state, eligible: 5, embedded: 2, processing: 3, failed: 0, candidates: 0, enqueued: 0, capped: false, ...extra });

test("상태별로 처리 중·사진 부족·실패·완료·동의 필요를 구분해 보인다", () => {
  assert.equal(generationView(gen("needs_consent")).kind, "needs_consent");
  assert.equal(generationView(gen("needs_consent")).button, null);
  const few = generationView(gen("not_enough_photos", { eligible: 2 }));
  assert.match(few.text, /3장 이상.*2장/);
  assert.equal(few.button, null); // 사진이 모자라면 누를 버튼이 없다
  const working = generationView(gen("processing"));
  assert.equal(working.text, "사진을 살펴보는 중이에요 (2/5장)");
  assert.equal(working.spinner, true);
  assert.equal(working.button, null); // 처리 중에는 다시 누를 수 없다(중복 요청 방지)
  assert.equal(generationView(gen("failed", { failed: 2 })).text, GENERATION_LABELS.failed);
  assert.equal(generationView(gen("failed")).button, null);
});

test("준비 전에는 만들기, 준비 뒤에는 다시 확인하기 버튼이 보이고 요청 중에는 버튼이 사라진다", () => {
  assert.equal(generationView(gen("idle")).button, "create");
  assert.equal(generationView(gen("idle"), { busy: true }).button, null);
  assert.equal(generationView(gen("idle"), { busy: true }).spinner, true);
  const ready = generationView(gen("ready", { candidates: 2 }));
  assert.equal(ready.text, "추억 후보 2개를 찾았어요");
  assert.equal(ready.button, "recheck");
  assert.match(generationView(gen("ready", { candidates: 0 })).text, /찾지 못했어요/);
  assert.equal(generationView(gen("ready"), { polling: true }).button, null);
});

test("상태가 없거나 모르는 값이면 패널을 보이지 않는다", () => {
  assert.equal(generationView(null).visible, false);
  assert.equal(generationView({}).visible, false);
  assert.equal(generationView({ state: "weird" }).visible, false);
});

test("404 와 generation_not_open 은 패널을 숨기고 동의 필요·네트워크·만료는 각각 다른 문구가 된다", () => {
  assert.equal(generationError({ status: 404 }).hidden, true);
  assert.equal(generationError({ status: 403, code: "generation_not_open" }).hidden, true);
  assert.equal(generationError({ status: 403, code: "consent_required" }).message, GENERATION_LABELS.needsConsent);
  assert.equal(generationError({ status: 403, code: "consent_required" }).hidden, false);
  assert.match(generationError({ status: 403, code: "family_off" }).message, /켜져 있지 않아요/);
  assert.match(generationError({ status: 0 }).message, /연결/);
  assert.match(generationError({ status: 401 }).message, /로그인/);
  assert.match(generationError({ status: 500 }).message, /다시 시도/);
});

test("처리 중일 때만, 최대 횟수 전까지만 진행을 확인한다", () => {
  assert.equal(shouldKeepPolling(gen("processing"), 0), true);
  assert.equal(shouldKeepPolling(gen("processing"), GENERATION_POLL_MAX - 1), true);
  assert.equal(shouldKeepPolling(gen("processing"), GENERATION_POLL_MAX), false); // 무한 확인 방지
  for (const s of ["ready", "failed", "idle", "needs_consent", "not_enough_photos"]) assert.equal(shouldKeepPolling(gen(s), 0), false);
  assert.equal(shouldKeepPolling(null, 0), false);
});

test("후보가 새로 생기거나 수가 달라졌을 때만 목록을 다시 불러온다", () => {
  assert.equal(shouldReloadCandidates(gen("processing"), gen("ready", { candidates: 1 })), true);
  assert.equal(shouldReloadCandidates(null, gen("ready", { candidates: 1 })), true);
  assert.equal(shouldReloadCandidates(gen("ready", { candidates: 1 }), gen("ready", { candidates: 1 })), false); // 같은 결과로 반복 확인
  assert.equal(shouldReloadCandidates(gen("ready", { candidates: 1 }), gen("ready", { candidates: 2 })), true);
  assert.equal(shouldReloadCandidates(gen("idle"), gen("processing")), false);
});

test("가족·사용자가 바뀌면 이전 가족의 생성 상태를 비우고 늦게 온 응답은 버린다", () => {
  let s = generationReducer(initialGenerationState(), { type: "scope", scope: "u1:g1", seq: 1 });
  s = generationReducer(s, { type: "start", seq: 1 });
  assert.equal(s.busy, true);
  s = generationReducer(s, { type: "ok", seq: 1, gen: gen("ready", { candidates: 3 }) });
  assert.equal(s.gen.candidates, 3);
  s = generationReducer(s, { type: "scope", scope: "u1:g2", seq: 2 }); // 다른 가족으로 전환
  assert.equal(s.gen, null);
  assert.equal(s.busy, false);
  const late = generationReducer(s, { type: "ok", seq: 1, gen: gen("ready", { candidates: 3 }) }); // 이전 가족의 늦은 응답
  assert.equal(late.gen, null);
  const out = generationReducer(s, { type: "scope", scope: null, seq: 3 }); // 로그아웃
  assert.equal(out.gen, null);
  assert.equal(out.scope, null);
});

test("404 응답은 패널을 숨기고, 다른 오류는 문구를 남긴다", () => {
  let s = generationReducer(initialGenerationState(), { type: "scope", scope: "u1:g1", seq: 1 });
  s = generationReducer(s, { type: "fail", seq: 1, error: { status: 404 } });
  assert.equal(s.hidden, true);
  assert.equal(s.error, null);
  let t = generationReducer(initialGenerationState(), { type: "scope", scope: "u1:g1", seq: 1 });
  t = generationReducer(t, { type: "fail", seq: 1, error: { status: 0 } });
  assert.equal(t.hidden, false);
  assert.match(t.error, /연결/);
  t = generationReducer(t, { type: "ok", seq: 1, gen: gen("idle") }); // 다시 성공하면 오류가 사라진다
  assert.equal(t.error, null);
});