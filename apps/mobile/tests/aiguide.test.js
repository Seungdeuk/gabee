// 가비 AI 이용 안내 문구 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AI_GUIDE_FEATURES,
  AI_GUIDE_HOW_TO,
  AI_GUIDE_PRIVACY,
  AI_GUIDE_SOURCES,
} from "../src/features/more/aiGuide.js";
import { MENU, itemAction } from "../src/features/more/menuItems.js";

test("가비 AI 이용 안내 메뉴는 /ai-guide 로 간다", () => {
  const item = MENU.find((i) => i.key === "ai");
  assert.deepEqual(itemAction(item), { type: "route", path: "/ai-guide" });
});

test("1:1 대화는 참고하지 않는 정보에 있고 참고하는 정보에는 없다", () => {
  assert.ok(AI_GUIDE_SOURCES.unused.some((t) => t.includes("1:1")));
  assert.ok(!AI_GUIDE_SOURCES.used.some((t) => t.includes("1:1")));
  assert.ok(AI_GUIDE_HOW_TO.note.includes("1:1"));
});

test("개인정보 안내에 외부 AI 전달과 가림의 한계가 들어 있다", () => {
  const all = AI_GUIDE_PRIVACY.join(" ");
  assert.ok(all.includes("외부 AI"));
  assert.ok(all.includes("놓칠 수"));
  assert.ok(all.includes("종단간 암호화가 아니"));
});

test("항목 키와 문구가 겹치지 않고 비어 있지 않다", () => {
  const keys = AI_GUIDE_FEATURES.map((f) => f.key);
  assert.equal(new Set(keys).size, keys.length);
  for (const f of AI_GUIDE_FEATURES) assert.ok(f.title && f.description && f.icon);
  for (const e of AI_GUIDE_HOW_TO.examples) assert.ok(e.startsWith("@가비 "));
});

test("대화 분석 안내(바로 전달·약 10분 저장)가 이용 안내에 있다", () => {
  const all = AI_GUIDE_PRIVACY.join(" ");
  assert.match(all, /별도 확인 없이 바로 AI로 전달/);
  assert.match(all, /약 10분\) 저장/);
});
