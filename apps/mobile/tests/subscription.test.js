// 구독 관리·문서함 메뉴 구성 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { MENU, SHORTCUTS, itemAction } from "../src/features/more/menuItems.js";

test("구독 관리 메뉴는 /subscription 으로 가고 문서함 줄에 가정통신문이 없다", () => {
  const sub = SHORTCUTS.find((i) => i.key === "subscription");
  assert.deepEqual(itemAction(sub), { type: "route", path: "/subscription" });
  const docs = MENU.find((i) => i.key === "docs");
  assert.equal(docs.subtitle, "가족 공지 · 업로드");
});
