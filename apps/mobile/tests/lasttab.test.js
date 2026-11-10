// 알림함에서 뒤로 갈 때 돌아갈 "마지막으로 보던 탭" 기억 규칙을 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { backTarget, lastTabPath, rememberTab } from "../src/shared/navigation/lastTab.js";

test("기억한 탭이 없으면 AI 채팅 탭이 기본이다", () => {
  assert.equal(lastTabPath(), "/chat");
});

test("탭 다섯 개는 각자의 경로로 기억된다", () => {
  const expected = { chat: "/chat", "family-chat": "/family-chat", schedule: "/schedule", care: "/care", my: "/my" };
  for (const [name, path] of Object.entries(expected)) {
    rememberTab(name);
    assert.equal(lastTabPath(), path);
  }
});

test("탭이 아닌 이름은 무시하고 직전에 기억한 탭을 그대로 둔다", () => {
  rememberTab("schedule");
  rememberTab("notifications");
  rememberTab("toString"); // 객체 기본 속성 이름도 탭이 아니다
  rememberTab(undefined);
  assert.equal(lastTabPath(), "/schedule");
});

test("backTarget: 돌아갈 화면이 있으면 back, 없으면 탭 경로", () => {
  assert.equal(backTarget(true, "/care"), "back");
  assert.equal(backTarget(false, "/care"), "/care");
  assert.equal(backTarget(false, lastTabPath()), lastTabPath());
});
