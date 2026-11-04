// AI 사용량 게이지 계산 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { USAGE_HIGH_RATIO, usageGauges, usedRatio } from "../src/shared/aiUsage.js";

test("사용한 비율은 0~1 로 자른다", () => {
  assert.equal(usedRatio(10, 3), 0.3);
  assert.equal(usedRatio(10, 0), 0);
  assert.equal(usedRatio(10, 25), 1);
  assert.equal(usedRatio(10, -4), 0);
});

test("한도·사용량을 모르거나 한도가 0 이하이면 null", () => {
  for (const [l, u] of [[undefined, 1], [10, undefined], [0, 0], [-5, 1], ["10", 1], [null, null]]) assert.equal(usedRatio(l, u), null);
});

test("게이지는 나·가족 두 줄이고 80% 이상일 때만 high, 퍼센트는 반올림", () => {
  const g = usageGauges({ userUsed: USAGE_HIGH_RATIO, groupUsed: 0.02 });
  assert.deepEqual(g.map((x) => [x.key, x.label, x.percent, x.high]), [["me", "나", 80, true], ["family", "가족", 2, false]]);
  assert.deepEqual(usageGauges({ userUsed: null, groupUsed: 0.5 }), []);
});
