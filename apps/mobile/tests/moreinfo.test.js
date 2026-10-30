// 마이 페이지 앱 버전 문구 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { versionText } from "../src/features/more/appInfo.js";

test("버전 앞에 v 를 붙인다", () => {
  assert.equal(versionText("1.0.0"), "v1.0.0");
});

test("이미 v 가 있으면 두 번 붙이지 않는다", () => {
  assert.equal(versionText("v1.2.3"), "v1.2.3");
  assert.equal(versionText(" V2.0 "), "v2.0");
});

test("버전을 알 수 없으면 안내 문구를 돌려준다", () => {
  for (const v of [undefined, null, "", "  ", 3]) assert.equal(versionText(v), "확인할 수 없어요");
});
