// mock 모드(개발용 합성 후보)에서는 가짜 사진 id 가 서버에서 404 를 받아도 후보에서 사진을 빼지 않는다(BlueStacks 실행에서 발견: 카드가 몇 초 뒤 전부 사라졌다). npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { mockCandidatesResponse } from "../src/features/family-memory/fixtures.js";
import { initialMemoriesState, memoriesReducer, photoGoneAction } from "../src/features/family-memory/memories.js";

const loaded = () => memoriesReducer(memoriesReducer(initialMemoriesState(), { type: "scope", scope: "u:g", seq: 1 }), { type: "ok", seq: 1, items: mockCandidatesResponse().items });

test("mock 모드: 사진 로딩 실패는 후보를 줄이지 않는다", () => {
  const state = loaded();
  assert.equal(state.items.length, 3);
  const action = photoGoneAction("mock", "mock-camp", "mock-a1");
  assert.equal(action, null);
});

test("on 모드: 사진 로딩 실패는 기존처럼 그 사진을 후보에서 뺀다", () => {
  const state = loaded();
  const action = photoGoneAction("on", "mock-camp", "mock-a2");
  assert.deepEqual(action, { type: "photoGone", candidateId: "mock-camp", attachmentId: "mock-a2" });
  const next = memoriesReducer(state, action);
  assert.equal(next.items.find((c) => c.id === "mock-camp").photo_count, 4);
});
