import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { recentChatLines } from "../src/features/schedule/suggest_chat.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const DAY = 24 * 60 * 60 * 1000;
const NOW = Date.UTC(2026, 9, 29, 12, 0, 0);
const user = (text, extra = {}) => ({ id: "m", role: "user", text, ...extra });
const ai = (text) => ({ id: "a", role: "assistant", text });

test("사용자 말만 고르고 AI 답은 뺀다", () => {
  const sessions = [{ id: "1", updatedAt: NOW, messages: [user("엄마 병원 가야 해"), ai("알겠어요"), user("여권 갱신")] }];
  assert.deepEqual(recentChatLines(sessions, NOW), ["여권 갱신", "엄마 병원 가야 해"]);
});

test("7일 경계: 정확히 7일 전은 포함, 그보다 오래면 제외", () => {
  const sessions = [
    { id: "1", updatedAt: NOW - 7 * DAY, messages: [user("경계")] },
    { id: "2", updatedAt: NOW - 7 * DAY - 1, messages: [user("너무 오래")] },
  ];
  assert.deepEqual(recentChatLines(sessions, NOW), ["경계"]);
});

test("메시지 시각이 있으면 그 시각, 없으면 대화 updatedAt 을 쓴다", () => {
  const sessions = [
    { id: "1", updatedAt: NOW, messages: [user("옛 말", { at: NOW - 11 * DAY }), user("시각 없음")] },
    { id: "2", updatedAt: NOW - 20 * DAY, messages: [user("최근 말", { createdAt: NOW - DAY }), user("오래된 대화")] },
  ];
  assert.deepEqual(recentChatLines(sessions, NOW), ["시각 없음", "최근 말"]);
});

test("최신순으로 최대 30줄", () => {
  const sessions = Array.from({ length: 40 }, (_, i) => ({ id: String(i), updatedAt: NOW - i * 1000, messages: [user(`말 ${i}`)] }));
  const lines = recentChatLines(sessions, NOW);
  assert.equal(lines.length, 30);
  assert.equal(lines[0], "말 0");
  assert.equal(lines[29], "말 29");
});

test("앞뒤 공백을 다듬고 200자로 자르며 빈 줄과 중복은 버린다", () => {
  const long = "가".repeat(250);
  const sessions = [{ id: "1", updatedAt: NOW, messages: [user("  같은 말  "), user("   "), user("같은 말"), user(long), user("")] }];
  const lines = recentChatLines(sessions, NOW);
  assert.deepEqual(lines, ["가".repeat(200), "같은 말"]);
});

test("세션이 이상하면 빈 배열", () => {
  assert.deepEqual(recentChatLines(null, NOW), []);
  assert.deepEqual(recentChatLines([{ id: "1", updatedAt: NOW }, null], NOW), []);
});

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("listSuggestions 는 POST 로 { chat } 본문을 보낸다(없으면 빈 배열)", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method, body: init.body });
    return new Response(JSON.stringify({ suggestions: [], exhausted: false }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const { listSuggestions } = await import("../src/features/schedule/api.js?suggest");
  assert.deepEqual(await listSuggestions(["여권 갱신"]), { suggestions: [], exhausted: false });
  await listSuggestions();
  assert.equal(calls[0].path, "/schedule/suggestions");
  assert.equal(calls[0].method, "POST");
  assert.deepEqual(JSON.parse(calls[0].body), { chat: ["여권 갱신"] });
  assert.deepEqual(JSON.parse(calls[1].body), { chat: [] });
});
