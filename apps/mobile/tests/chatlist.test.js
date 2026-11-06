// 소통 탭 목록 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { formatRoomTime, matchesQuery, roomA11yLabel } from "../src/features/family-chat/listUtils.js";

const at = (y, mo, d, h, mi) => new Date(y, mo - 1, d, h, mi).toISOString();

test("formatRoomTime: 오늘·어제·그 외", () => {
  const now = new Date(2026, 9, 23, 18, 0);
  assert.equal(formatRoomTime(at(2026, 10, 23, 15, 20), now), "오후 3:20");
  assert.equal(formatRoomTime(at(2026, 10, 22, 9, 0), now), "어제");
  assert.equal(formatRoomTime(at(2026, 10, 21, 9, 0), now), "10월 21일");
  assert.equal(formatRoomTime("엉터리", now), "");
});

test("matchesQuery·roomA11yLabel", () => {
  assert.equal(matchesQuery("우리 가족", " 가족 "), true);
  assert.equal(matchesQuery("우리 가족", "친구"), false);
  assert.equal(matchesQuery("우리 가족", ""), true);
  assert.equal(roomA11yLabel("안녕"), "가족 채팅방, 마지막 메시지 안녕");
});

test("소통 탭 상단: 돋보기 버튼과 검색 토글은 없고 검색창은 항상 보이며, 새 대화 버튼은 제목 줄 높이와 무관하게 고정된다", () => {
  const read = (rel) => readFileSync(new URL(`../src/features/family-chat/${rel}`, import.meta.url), "utf8");
  const header = read("components/ChatListHeader.js");
  assert.doesNotMatch(header, /label=\{searching|name=\{searching|onToggleSearch|autoFocus/); // 돋보기·닫기 토글과 자동 포커스가 없다
  assert.match(header, /accessibilityLabel="채팅 검색"/); // 검색창은 남는다
  assert.match(header, /position: "absolute", top: -SETTINGS_RAISE/); // 제목 높이에 따라 내려가지 않는다
  const screen = read("screens/FamilyChatScreen.js");
  assert.doesNotMatch(screen, /setSearching|toggleSearch/);
  assert.match(screen, /state\.status === "ready" && query\.trim\(\) \?/); // 입력이 있으면 대화 내용 결과를 보인다
});
