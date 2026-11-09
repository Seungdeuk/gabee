// AI 채팅 탭: 오류 코드별 안내 문구, 대화 이력에서 오류 말풍선 제외, AI 설정 API 호출 모양을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  AI_OFF_BODY,
  AI_OFF_TITLE,
  assistantErrorText,
  errorMessage,
  historyForServer,
} from "../src/features/ai-assistant/errors.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("오류 코드별 안내 문구", () => {
  assert.equal(assistantErrorText({ code: "ai_not_enabled" }), AI_OFF_TITLE);
  assert.match(assistantErrorText({ code: "ai_cooldown" }), /조금 뒤에 다시 물어봐 주세요/);
  assert.match(assistantErrorText({ code: "ai_busy" }), /조금 뒤에 다시 물어봐 주세요/);
  assert.match(assistantErrorText({ code: "ai_daily_limit_user" }), /오늘 AI 사용 한도에 도달했어요/);
  assert.match(assistantErrorText({ code: "ai_daily_limit_group" }), /오늘 AI 사용 한도에 도달했어요/);
  assert.match(assistantErrorText({ code: "llm_failed" }), /AI 연결에 문제가 있어요/);
  assert.match(assistantErrorText({ code: "not_member" }), /가족 그룹에 참여/);
  assert.equal(assistantErrorText({ code: "x", message: "서버 문구" }), "서버 문구");
  assert.match(assistantErrorText(null), /답변을 가져오지 못했어요/);
});

test("안내 카드 문구에는 외부 AI 전송 설명과 민감 기록 제외가 들어 있다", () => {
  assert.match(AI_OFF_BODY, /외부 AI\(Anthropic\)로 전송/);
  assert.match(AI_OFF_BODY, /민감한 기록도/); // 민감 기록도 가린 글이 전송될 수 있다(CHAT_INCLUDE_SENSITIVE 기본 켜짐)
  assert.doesNotMatch(AI_OFF_BODY, /기본으로 제외/);
  assert.match(AI_OFF_BODY, /소유자나 관리자가 켤 수 있어요/);
});

test("오류 말풍선: ai_not_enabled 만 안내 카드(aiOff)가 된다", () => {
  assert.equal(errorMessage("1", { code: "ai_not_enabled" }).aiOff, true);
  const other = errorMessage("2", { code: "llm_failed" });
  assert.equal(other.aiOff, undefined);
  assert.equal(other.isError, true);
});

test("서버로 보내는 대화 이력에서 오류 말풍선과 답을 못 받은 질문은 빠진다", () => {
  const messages = [
    { id: "0", role: "user", text: "전기요금" },
    { id: "1", role: "assistant", text: "48,200원이에요", sources: [] },
    { id: "2", role: "user", text: "수도요금" },
    { id: "3", role: "assistant", text: "조금 뒤에 다시 물어봐 주세요.", isError: true },
    { id: "4", role: "user", text: "수도요금 다시" },
    { id: "5", role: "assistant", text: "AI 도우미가 꺼져 있어요", isError: true, aiOff: true },
  ];
  assert.deepEqual(historyForServer(messages), [
    { role: "user", text: "전기요금" },
    { role: "assistant", text: "48,200원이에요" },
  ]);
  const text = JSON.stringify(historyForServer(messages));
  assert.ok(!text.includes("다시 물어봐") && !text.includes("꺼져 있어요"));
});

test("AI 설정 API: GET 으로 확인하고, 켤 때만 PUT {enabled:true}", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null });
    return new Response(JSON.stringify({ enabled: false, can_manage: true }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const api = await import("../src/features/ai-assistant/api.js");
  assert.deepEqual(await api.getAiSettings(), { enabled: false, canManage: true });
  assert.equal(calls.length, 1); // 설정을 읽는 것만으로는 켜지 않는다
  await api.enableAi();
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.path}`),
    ["GET /family-chat/ai/settings", "PUT /family-chat/ai/settings"],
  );
  assert.deepEqual(calls[1].body, { enabled: true });
});
