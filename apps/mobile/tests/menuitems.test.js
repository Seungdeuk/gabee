// 마이 페이지 메뉴 항목·동작 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { MENU, MENU_SECTIONS, SHORTCUTS, itemAction, menuSections, profileSubtitle } from "../src/features/more/menuItems.js";

const byKey = (list, key) => list.find((i) => i.key === key);

test("바로가기는 4칸, 목록은 7줄이고 key 가 겹치지 않는다", () => {
  assert.equal(SHORTCUTS.length, 4);
  assert.equal(MENU.length, 7);
  const keys = [...SHORTCUTS, ...MENU].map((i) => i.key);
  assert.equal(new Set(keys).size, keys.length);
});

test("항목 제목 순서", () => {
  assert.deepEqual(
    SHORTCUTS.map((i) => i.title),
    ["AI 리포트", "가족 랭킹", "구독 관리", "가족 초대"],
  );
  assert.deepEqual(
    MENU.map((i) => i.title),
    ["우리 가족", "가족 공유 문서함", "가비 AI 이용 안내", "계정 및 보안", "공지사항", "고객센터", "서비스 정보"],
  );
});

test("route 가 있는 항목은 이동 동작을 돌려준다", () => {
  assert.deepEqual(itemAction(byKey(MENU, "family")), { type: "route", path: "/family" });
  assert.deepEqual(itemAction(byKey(MENU, "account")), { type: "route", path: "/account-security" });
  assert.deepEqual(itemAction(byKey(SHORTCUTS, "report")), { type: "route", path: "/report" });
});

test("준비 중 항목과 잘못된 입력은 soon 이다", () => {
  assert.deepEqual(itemAction(byKey(SHORTCUTS, "settings")), { type: "soon" });
  assert.deepEqual(itemAction(byKey(SHORTCUTS, "ranking")), { type: "soon" });
  assert.deepEqual(itemAction(undefined), { type: "soon" });
  assert.deepEqual(itemAction({}), { type: "soon" });
  assert.deepEqual(itemAction({ route: "" }), { type: "soon" });
  assert.deepEqual(itemAction({ soon: true, route: "/x" }), { type: "soon" });
});

test("soon 이 아닌 항목은 / 로 시작하는 route 가 있다", () => {
  for (const item of [...SHORTCUTS, ...MENU].filter((i) => !i.soon)) {
    assert.equal(typeof item.route, "string", item.key);
    assert.ok(item.route.startsWith("/"), item.key);
  }
});

test("프로필 둘째 줄 문구", () => {
  assert.equal(profileSubtitle("우리 가족", "관리자"), "우리 가족 · 관리자");
  assert.equal(profileSubtitle("우리 가족", null), "우리 가족");
  assert.equal(profileSubtitle(undefined, "엄마"), "엄마");
  assert.equal(profileSubtitle("  우리 가족  ", "   "), "우리 가족");
  assert.equal(profileSubtitle(123, {}), "가족 그룹에 참여해 보세요");
  assert.equal(profileSubtitle("", ""), "가족 그룹에 참여해 보세요");
  assert.equal(profileSubtitle(null, undefined), "가족 그룹에 참여해 보세요");
});

test("목록은 가족 및 AI 서비스 3줄, 계정 및 고객지원 4줄로 묶인다", () => {
  const sections = menuSections(MENU);
  assert.deepEqual(sections.map((x) => x.title), ["가족 및 AI 서비스", "계정 및 고객지원"]);
  assert.deepEqual(sections.map((x) => x.items.map((i) => i.title)), [
    ["우리 가족", "가족 공유 문서함", "가비 AI 이용 안내"],
    ["계정 및 보안", "공지사항", "고객센터", "서비스 정보"],
  ]);
  // 모든 항목이 정의된 묶음에 들어간다
  const known = new Set(MENU_SECTIONS.map((x) => x.key));
  for (const item of MENU) assert.ok(known.has(item.section), item.key);
  // 항목이 없는 묶음은 빠진다
  assert.deepEqual(menuSections([]), []);
});
