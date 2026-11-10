// 소통 탭 방 목록 주기 새로고침 간격 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { ROOM_REFRESH_MS } from "../src/features/family-chat/listUtils.js";

const TAB_TOTAL_POLL_MS = 30000; // useTotalUnread.js 의 UNREAD_POLL_MS (그 파일은 expo-router 를 불러와 노드 시험에서 못 읽는다)

test("ROOM_REFRESH_MS: 너무 짧아 서버를 괴롭히지 않고, 하단 탭 합계 갱신(30초)보다는 자주 갱신한다", () => {
  assert.ok(ROOM_REFRESH_MS >= 5000, "5초 미만이면 폴링 부담이 크다");
  assert.ok(ROOM_REFRESH_MS < TAB_TOTAL_POLL_MS, "방 숫자가 하단 탭 숫자보다 늦게 따라오지 않게 한다");
});
