// 가족 나가기: 소유자는 다른 구성원이 있으면 못 나가고, 혼자일 때만 가족 데이터를 모두 지우고 나간다(확인 문구가 다르다): npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const src = (p) => readFileSync(new URL(`../src/features/family-group/${p}`, import.meta.url), "utf8");

test("leaveMode: 구성원은 그냥 나가고, 소유자는 혼자일 때만 가족을 지우고 나가며, 다른 구성원이 있으면 막는다", async () => {
  const { leaveMode } = await import("../src/features/family-group/leaveMode.js");
  assert.equal(leaveMode({ isOwner: false, memberCount: 3 }), "member");
  assert.equal(leaveMode({ isOwner: true, memberCount: 3 }), "blocked");
  assert.equal(leaveMode({ isOwner: true, memberCount: 2 }), "blocked");
  assert.equal(leaveMode({ isOwner: true, memberCount: 1 }), "last");
  assert.equal(leaveMode({ isOwner: true, memberCount: 0 }), "last");
});

test("나가기 화면: 혼자인 소유자에게는 '모든 데이터가 삭제되고 되돌릴 수 없어요' 확인을 거친다", () => {
  const section = src("components/LeaveFamilySection.js");
  assert.match(section, /leaveMode\(\{ isOwner, memberCount \}\)/);
  assert.match(section, /되돌릴 수 없/);
  assert.match(section, /삭제하고 나가기/);
  assert.match(src("screens/FamilyScreen.js"), /<LeaveFamilySection isOwner=\{group\.my_role === "owner"\} memberCount=\{group\.members\.length\}/);
});
