// 1:1 방에서도 AI 도우미를 쓴다: 분석 요청에 방 id 를 싣고, 1:1 방에서도 버튼이 보이며, 상대가 가족을 나갔으면 안내 문구가 나온다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import { chatErrorMessage } from "../src/features/family-chat/messages.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";
// 서버 주소는 불러올 때 읽으므로 환경 변수를 정한 뒤에 가져온다
const { analyzeChat } = await import("../src/features/family-chat/api.js");

const realFetch = globalThis.fetch;
const calls = [];
beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: init.body ? JSON.parse(init.body) : null });
    return new Response(JSON.stringify({ summary: "", important_messages: [], schedule_candidates: [], todo_candidates: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8").replace(/\r\n/g, "\n");

test("analyzeChat: 1:1 방이면 room_id 를 싣고, 가족 전체방 요청은 이전과 같은 본문이다", async () => {
  await analyzeChat({ roomId: "room-1" });
  await analyzeChat({ limit: 50, afterId: 7, roomId: "room-1" });
  await analyzeChat(); // 가족 전체방
  await analyzeChat({ roomId: undefined });
  assert.deepEqual(calls[0].body, { limit: 100, after_id: 0, room_id: "room-1" });
  assert.deepEqual(calls[1].body, { limit: 50, after_id: 7, room_id: "room-1" });
  assert.deepEqual(calls[2].body, { limit: 100, after_id: 0 }); // room_id 키가 없다
  assert.deepEqual(calls[3].body, { limit: 100, after_id: 0 });
});

test("chatErrorMessage: 상대가 가족을 나갔으면(peer_left) 그 이유를 알려 준다", () => {
  assert.match(chatErrorMessage({ code: "peer_left" }), /가족을 나가/);
});

test("ChatRoomScreen: 1:1 방에서도 AI 도우미 버튼이 보이고 AiPanel 에 방 id 를 넘긴다(소스 확인)", () => {
  const screen = read("../src/features/family-chat/screens/ChatRoomScreen.js");
  assert.doesNotMatch(screen, /direct \? null : <IconButton name="sparkles-outline"/); // 1:1 에서 숨기지 않는다
  assert.match(screen, /<IconButton name="sparkles-outline" label="AI 도우미 열기"/);
  assert.doesNotMatch(screen, /direct \? null : <AiPanel/);
  assert.match(screen, /<AiPanel visible=\{aiOpen\}[^\n]*roomId=\{roomId \?\? undefined\} \/>/); // 1:1 방이면 그 방 id, 가족 전체방은 없음
  const panel = read("../src/features/family-chat/components/AiPanel.js");
  assert.match(panel, /return analyzeChat\(\{ roomId \}\)/);
});
