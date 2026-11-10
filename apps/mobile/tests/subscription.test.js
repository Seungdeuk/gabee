// 구독 관리·문서함 메뉴 구성 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { MENU, SHORTCUTS, itemAction } from "../src/features/more/menuItems.js";

test("구독 관리 메뉴는 /subscription 으로 가고 가족 위치 확인 줄은 준비 중이다", () => {
  const sub = SHORTCUTS.find((i) => i.key === "subscription");
  assert.deepEqual(itemAction(sub), { type: "route", path: "/subscription" });
  const docs = MENU.find((i) => i.key === "docs");
  assert.equal(docs.title, "가족 위치 확인");
  assert.equal(docs.soon, true); // 위치 확인 기능은 아직 없다
});
