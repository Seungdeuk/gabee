// 가족 채팅 AI: 오류 문구·결과 설명·일정 후보 판정과 API 호출을 가짜 서버(fetch 대체)로 시험한다: npm test
import { usageGauges } from "../src/shared/aiUsage.js";
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  canRegisterSchedule,
  chatErrorMessage,
  parseAiSettings,
  rangeCaption,
  resultCaption,
  scheduleMissingNote,
  shouldLoadSettings,
} from "../src/features/family-chat/messages.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("AI 오류 문구: 서버 코드를 사용자 문장으로, 대화 내용은 넣지 않는다", () => {
  assert.match(chatErrorMessage({ code: "ai_not_enabled" }), /다시 눌러 주세요/);
  assert.match(chatErrorMessage({ code: "not_manager" }), /관리자/);
  assert.match(chatErrorMessage({ code: "ai_cooldown", retryAfter: 30 }), /30초/);
  assert.match(chatErrorMessage({ code: "ai_cooldown", retryAfter: 90 }), /2분/);
  assert.match(chatErrorMessage({ code: "ai_daily_limit_user" }), /내가/);
  assert.match(chatErrorMessage({ code: "ai_daily_limit_group" }), /가족이/);
  assert.match(chatErrorMessage({ code: "ai_busy" }), /처리되고/);
  assert.match(chatErrorMessage({ code: "llm_unavailable" }), /설정되지 않았어요/);
  assert.match(chatErrorMessage({ code: "llm_failed" }), /다시 시도/);
  assert.match(chatErrorMessage({ code: "too_few_messages" }), /충분하지 않아요/);
  assert.match(chatErrorMessage({ code: "no_group" }), /가족 그룹/);
  assert.match(chatErrorMessage({ code: "network_error" }), /연결하지 못했어요/);
  assert.equal(chatErrorMessage({ code: "new_code", message: "서버 문구" }), "서버 문구");
  assert.equal(chatErrorMessage(null), "");
});

test("결과 설명: 캐시면 AI 호출 없음, 아니면 방금 분석과 호출 수·토큰", () => {
  assert.equal(resultCaption({ cached: true, api_calls: 0 }), "저장된 결과(AI 호출 없음)");
  assert.equal(resultCaption({ cached: false, api_calls: 1, input_tokens: 300, output_tokens: 120 }), "방금 분석 · AI 호출 1번 · 토큰 420");
  assert.equal(resultCaption(null), "");
  const caption = rangeCaption({ message_count: 24, generated_at: new Date(2026, 9, 23, 15, 20).toISOString() });
  assert.equal(caption, "대화 24개 기준 · 오후 3:20");
  assert.equal(rangeCaption({ message_count: 5, generated_at: "not-a-date" }), "대화 5개 기준");
});

test("일정 후보 등록 가능 판정: 날짜·시간이 둘 다 있을 때만", () => {
  assert.equal(canRegisterSchedule({ title: "병원", date: "2026-11-02", time: "14:30" }), true);
  assert.equal(canRegisterSchedule({ title: "병원", date: "2026-11-02", time: null }), false);
  assert.equal(canRegisterSchedule({ title: "병원", date: null, time: "14:30" }), false);
  assert.equal(canRegisterSchedule(null), false);
  assert.equal(scheduleMissingNote({ date: null, time: null }), "날짜·시간이 정해지지 않았어요");
  assert.equal(scheduleMissingNote({ date: "2026-11-02", time: "14:30" }), "");
});

test("설정 응답 해석: 동의·권한·남은 횟수", () => {
  const s = parseAiSettings({
    enabled: true,
    can_manage: false,
    auto_analysis: false,
    limits: { user_per_day: 10, group_per_day: 30, cooldown_seconds: 30, cache_ttl_seconds: 600 },
    usage: { user_today: 3, group_today: 5 },
  });
  assert.deepEqual(s, { enabled: true, canManage: false, userLeft: 7, groupLeft: 25, userUsedRatio: 0.3, groupUsedRatio: 5 / 30, cooldownSeconds: 30 });
  assert.deepEqual(usageGauges({ userUsed: s.userUsedRatio, groupUsed: s.groupUsedRatio }).map((g) => [g.key, g.percent, g.high]), [["me", 30, false], ["family", 17, false]]);
  const over = parseAiSettings({ enabled: true, limits: { user_per_day: 2, group_per_day: 2 }, usage: { user_today: 5, group_today: 9 } });
  assert.equal(over.userLeft, 0);
  assert.equal(over.userUsedRatio, 1);
  assert.equal(usageGauges({ userUsed: over.userUsedRatio, groupUsed: over.groupUsedRatio })[0].high, true); // 다 썼으면 거의 다 썼어요 상태
  const bad = parseAiSettings({ enabled: true, limits: { user_per_day: 0, group_per_day: 5 }, usage: { user_today: 1, group_today: 1 } });
  assert.equal(bad.userUsedRatio, null); // 한도 0 은 비율을 알 수 없다
  const empty = parseAiSettings(null);
  assert.equal(empty.enabled, false);
  assert.equal(empty.canManage, false);
  assert.deepEqual(usageGauges({ userUsed: empty.userUsedRatio, groupUsed: empty.groupUsedRatio }), []);
});

test("AI 호출: 경로·메서드·본문, 대화 글자는 보내지 않고 Bearer 만", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} });
    return json(200, { enabled: true });
  };
  const client = await import("../src/shared/api/client.js");
  const api = await import("../src/features/family-chat/api.js");
  client.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  await api.getAiSettings();
  await api.setAiEnabled(true);
  await api.analyzeChat();
  await api.analyzeChat({ limit: 50, afterId: 7 });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.path}`),
    [
      "GET /family-chat/ai/settings",
      "PUT /family-chat/ai/settings",
      "POST /family-chat/ai/analysis",
      "POST /family-chat/ai/analysis",
    ],
  );
  assert.deepEqual(calls[1].body, { enabled: true });
  assert.deepEqual(calls[2].body, { limit: 100, after_id: 0 });
  assert.deepEqual(calls[3].body, { limit: 50, after_id: 7 });
  assert.equal(calls[2].headers.Authorization, "Bearer access-1");
  assert.equal(calls[2].headers["X-Gyeot-Token"], undefined);
});

test("일정 후보 등록: EventCreate 본문으로 POST /schedule/events, 날짜·시간이 없으면 호출하지 않는다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method, body: JSON.parse(init.body) });
    return json(200, { id: "e1" });
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.registerScheduleCandidate({ title: "병원", date: "2026-11-02", time: "14:30", place: "한빛의원", source_message_ids: [1] });
  assert.equal(calls.length, 1);
  assert.equal(`${calls[0].method} ${calls[0].path}`, "POST /schedule/events");
  const { title, starts_at: startsAt, note, status, source, ...rest } = calls[0].body;
  assert.deepEqual(rest, {}); // EventCreate 에 없는 필드는 보내지 않는다
  assert.equal(title, "병원");
  assert.equal(note, "장소: 한빛의원");
  assert.equal(status, "confirmed");
  assert.equal(source, "chat");
  assert.equal(new Date(startsAt).getTime(), new Date(2026, 10, 2, 14, 30).getTime());

  assert.equal(api.scheduleEventBody({ title: "병원", date: null, time: "14:30" }), null);
  assert.equal(api.scheduleEventBody({ title: "병원", date: "2026-02-31", time: "14:30" }), null);
  assert.equal(api.scheduleEventBody({ title: "병원", date: "2026-11-02", time: "25:00" }), null);
  await assert.rejects(() => api.registerScheduleCandidate({ title: "병원", date: null, time: null }));
  assert.equal(calls.length, 1);
});

test("AI 패널 호출 규칙: 닫혀 있으면 호출 없음, 열려도 설정만(분석·추천은 버튼)", () => {
  assert.equal(shouldLoadSettings(false), false);
  assert.equal(shouldLoadSettings(undefined), false);
  assert.equal(shouldLoadSettings(true), true);
});

test("parseAnalysis: replies·topics 가 있으면 그대로, 구 서버 응답(없음·null·배열 아님)은 빈 배열", async () => {
  const { parseAnalysis } = await import("../src/features/family-chat/messages.js");
  const full = parseAnalysis({ summary: "요약", important_messages: [], schedule_candidates: [{ title: "a" }], todo_candidates: [], replies: ["알겠어요", " ", 3], topics: ["주말 계획"], meta: { cached: false } });
  assert.deepEqual(full.replies, ["알겠어요"]);
  assert.deepEqual(full.topics, ["주말 계획"]);
  assert.equal(full.summary, "요약");
  assert.equal(full.schedule_candidates.length, 1);
  assert.deepEqual(full.meta, { cached: false });
  const old = parseAnalysis({ summary: "요약", important_messages: [], schedule_candidates: [], todo_candidates: [] });
  assert.deepEqual([old.replies, old.topics], [[], []]);
  const bad = parseAnalysis({ replies: null, topics: "x" });
  assert.deepEqual([bad.replies, bad.topics, bad.important_messages], [[], [], []]);
  assert.deepEqual(parseAnalysis(null).replies, []);
});
