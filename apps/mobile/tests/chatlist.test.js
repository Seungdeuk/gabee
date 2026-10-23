// 소통 탭 목록 순수 함수 시험: npm test
import assert from "node:assert/strict";
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
