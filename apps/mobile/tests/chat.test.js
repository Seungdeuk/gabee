// 가족 채팅 요약: 오류 문구·결과 설명과 API 호출을 가짜 서버(fetch 대체)로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { chatErrorMessage, summaryCaption } from "../src/features/family-chat/messages.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("요약 오류 문구: 서버 코드를 사용자 문장으로, 대화 내용은 넣지 않는다", () => {
  assert.match(chatErrorMessage({ code: "too_few_messages" }), /충분하지 않아요/);
  assert.match(chatErrorMessage({ code: "llm_unavailable" }), /설정되지 않았어요/);
  assert.match(chatErrorMessage({ code: "llm_failed" }), /다시 시도/);
  assert.match(chatErrorMessage({ code: "too_many_requests", retryAfter: 90 }), /2분/);
  assert.match(chatErrorMessage({ code: "too_many_requests", retryAfter: 30 }), /30초/);
  assert.equal(chatErrorMessage({ code: "new_code", message: "서버 문구" }), "서버 문구");
  assert.equal(chatErrorMessage(null), "");
});

test("요약 결과 설명: 메시지 수와 시각", () => {
  const caption = summaryCaption({ message_count: 24, generated_at: new Date(2026, 9, 23, 15, 20).toISOString() });
  assert.equal(caption, "최근 대화 24개 기준 · 오후 3:20");
  assert.equal(summaryCaption({ message_count: 5, generated_at: "not-a-date" }), "최근 대화 5개 기준");
});

test("요약 요청: 경로·본문, 로그인 세션이면 Bearer 만, 대화 글자는 보내지 않는다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method, body: JSON.parse(init.body), headers: init.headers ?? {} });
    return new Response(JSON.stringify({ summary: "- 요약", message_count: 3 }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const client = await import("../src/shared/api/client.js");
  const { summarizeChat } = await import("../src/features/family-chat/api.js");
  client.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  const res = await summarizeChat();
  await summarizeChat({ limit: 50, afterId: 7 });
  assert.equal(res.summary, "- 요약");
  assert.deepEqual(calls.map((c) => `${c.method} ${c.path}`), ["POST /family-chat/summary", "POST /family-chat/summary"]);
  assert.deepEqual(calls[0].body, { limit: 200, after_id: 0 }); // 대화 내용은 앱이 아니라 서버가 읽는다
  assert.deepEqual(calls[1].body, { limit: 50, after_id: 7 });
  assert.equal(calls[0].headers.Authorization, "Bearer access-1");
  assert.equal(calls[0].headers["X-Gyeot-Token"], undefined);
});
