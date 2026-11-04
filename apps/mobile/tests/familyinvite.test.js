// 가족 초대 화면: 일반 구성원에게 알려 줄 관리자 목록 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { managersOf } from "../src/features/family-group/messages.js";

test("소유자와 관리자만 골라 순서를 유지한다", () => {
  const members = [
    { id: "1", name: "엄마", group_role: "owner" },
    { id: "2", name: "민서", group_role: "member" },
    { id: "3", name: "아빠", group_role: "admin" },
  ];
  assert.deepEqual(managersOf(members).map((m) => m.name), ["엄마", "아빠"]);
});

test("구성원 목록이 없거나 잘못되면 빈 배열", () => {
  for (const v of [undefined, null, "x", {}, [null, {}]]) assert.deepEqual(managersOf(v), []);
});
