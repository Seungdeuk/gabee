// 가족 초대 화면: 일반 구성원에게 알려 줄 관리자 목록 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { FAMILY_NAME_MAX, managersOf, validateFamilyName } from "../src/features/family-group/messages.js";

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

test("가족 이름: 앞뒤 공백을 지우고 1~60자만 받는다", () => {
  assert.deepEqual(validateFamilyName("  행복한 우리집 "), { ok: true, value: "행복한 우리집" });
  assert.equal(validateFamilyName("가".repeat(FAMILY_NAME_MAX)).ok, true);
  for (const bad of ["", "   ", null, undefined, 3, "가".repeat(FAMILY_NAME_MAX + 1)]) assert.equal(validateFamilyName(bad).ok, false);
  assert.match(validateFamilyName("   ").error, /입력해 주세요/);
});
