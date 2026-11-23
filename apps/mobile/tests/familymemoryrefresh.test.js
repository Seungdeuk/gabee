// 철회 후 "다시 확인하기": 후보 수가 같아도(사진만 줄어도) 사용자가 직접 누르면 후보 목록을 다시 불러온다(BlueStacks 에서 발견). npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldReloadCandidates } from "../src/features/family-memory/generation.js";

const ready = (candidates) => ({ state: "ready", candidates });

test("자동 확인: ready 에서 후보 수가 그대로면 목록을 다시 부르지 않는다(기존 동작 유지)", () => {
  assert.equal(shouldReloadCandidates(ready(1), ready(1)), false);
  assert.equal(shouldReloadCandidates(ready(1), ready(1), false), false);
});

test("사용자가 직접 '다시 확인하기'를 누르면 후보 수가 같아도 ready 에서 목록을 다시 부른다", () => {
  assert.equal(shouldReloadCandidates(ready(1), ready(1), true), true);
});

test("직접 눌러도 ready 가 아니면(처리 중·실패) 목록을 부르지 않는다", () => {
  assert.equal(shouldReloadCandidates(ready(1), { state: "processing", candidates: 1 }, true), false);
  assert.equal(shouldReloadCandidates(null, null, true), false);
});