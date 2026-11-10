// 데일리 체크 전화 이야깃거리(AI 문구) 순수 함수 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_calltalk.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  FALLBACK_GREETINGS,
  callTalkKey,
  createCallTalkCache,
  provisionalPoints,
  shouldCacheCallTalk,
} from "../src/features/schedule/daily/logic.js";
import { callTalkFromServer } from "../src/features/schedule/daily/serverMap.js";

const walk = (count) => ({ name: "산책하기", type: "count", goal: 30, unit: "분", entry: { done: false, count } });
const pill = (done) => ({ name: "약 먹기", type: "check", goal: 1, entry: { done, count: 0, doneAt: done ? "09:00" : null } });

test("callTalkFromServer: AI 응답 한 쌍", () => {
  const out = callTalkFromServer({ source: "ai", reason: "", points: [{ say: " 산책 하셨네요 ", ask: " 어디 다녀오셨어요? " }] });
  assert.deepEqual(out, { source: "ai", reason: "", points: [{ say: "산책 하셨네요", ask: "어디 다녀오셨어요?" }] });
});

test("callTalkFromServer: 안부 문구는 ask 가 빈 채로 둔다", () => {
  const out = callTalkFromServer({ source: "greeting", reason: "limit", points: [{ say: "식사는 하셨어요?", ask: "" }] });
  assert.deepEqual(out, { source: "greeting", reason: "limit", points: [{ say: "식사는 하셨어요?", ask: "" }] });
});

test("callTalkFromServer: 빈 points·이상한 값·모르는 source", () => {
  assert.deepEqual(callTalkFromServer({ source: "greeting", reason: "no_habits", points: [] }).points, []);
  assert.deepEqual(callTalkFromServer(null), { source: "greeting", reason: "", points: [] });
  assert.deepEqual(callTalkFromServer({ source: "weird", reason: 3, points: "x" }), { source: "greeting", reason: "", points: [] });
  const out = callTalkFromServer({
    source: "ai",
    points: [{ say: 1, ask: "a" }, { say: "  ", ask: "b" }, null, { say: "가", ask: 5 }, { say: "나", ask: "다" }, { say: "라", ask: "마" }],
  });
  assert.deepEqual(out.points, [{ say: "가", ask: "" }, { say: "나", ask: "다" }]); // 이상한 줄은 버리고 최대 2개
});

const D = "2026-11-05";

test("callTalkKey: 같은 상태는 같은 키, 순서와 무관", () => {
  assert.equal(callTalkKey("mom", [walk(10), pill(true)], D), callTalkKey("mom", [pill(true), walk(10)], D));
  assert.notEqual(callTalkKey("mom", [pill(true)], D), callTalkKey("dad", [pill(true)], D));
});

test("callTalkKey: 체크·횟수가 바뀌면 다른 키", () => {
  assert.notEqual(callTalkKey("mom", [pill(false)], D), callTalkKey("mom", [pill(true)], D));
  assert.notEqual(callTalkKey("mom", [walk(10)], D), callTalkKey("mom", [walk(20)], D));
  assert.notEqual(callTalkKey("mom", [walk(20)], D), callTalkKey("mom", [walk(30)], D));
  assert.notEqual(callTalkKey("mom", [], D), callTalkKey("mom", [pill(false)], D));
});

test("callTalkKey: 날짜가 다르면 다른 키", () => {
  assert.notEqual(callTalkKey("mom", [pill(true)], D), callTalkKey("mom", [pill(true)], "2026-11-06"));
  assert.ok(callTalkKey("mom", [], D).startsWith(D));
});

test("FALLBACK_GREETINGS: 12~16개, 모두 28자 이내·중복 없음", () => {
  assert.ok(FALLBACK_GREETINGS.length >= 12 && FALLBACK_GREETINGS.length <= 16);
  assert.ok(FALLBACK_GREETINGS.every((t) => t.length > 0 && t.length <= 28));
  assert.equal(new Set(FALLBACK_GREETINGS).size, FALLBACK_GREETINGS.length);
});

test("provisionalPoints: 시드가 같으면 같은 결과, 기본 1개, ask 는 빈 글자", () => {
  assert.deepEqual(provisionalPoints(0.3), provisionalPoints(0.3));
  const one = provisionalPoints(0.5);
  assert.equal(one.length, 1);
  assert.equal(one[0].ask, "");
  assert.ok(FALLBACK_GREETINGS.includes(one[0].say));
  const two = provisionalPoints(0.999, 2); // 끝에서 처음으로 이어 붙는다
  assert.equal(two.length, 2);
  assert.notEqual(two[0].say, two[1].say);
  assert.equal(provisionalPoints(0)[0].say, FALLBACK_GREETINGS[0]);
  assert.equal(provisionalPoints(1)[0].say, FALLBACK_GREETINGS[FALLBACK_GREETINGS.length - 1]); // 범위 밖 시드도 안전
});

test("shouldCacheCallTalk: ai·no_habits·no_consent 는 두고 limit·error 안부는 두지 않는다", () => {
  assert.equal(shouldCacheCallTalk({ source: "ai", reason: "", points: [] }), true);
  assert.equal(shouldCacheCallTalk({ source: "greeting", reason: "no_habits", points: [] }), true);
  assert.equal(shouldCacheCallTalk({ source: "greeting", reason: "no_consent", points: [] }), true);
  assert.equal(shouldCacheCallTalk({ source: "greeting", reason: "limit", points: [] }), false);
  assert.equal(shouldCacheCallTalk({ source: "greeting", reason: "error", points: [] }), false);
});

test("createCallTalkCache: 저장·조회, 안 두는 결과, 용량 상한(오래된 것부터 제거)", () => {
  const cache = createCallTalkCache(2);
  const ai = (n) => ({ source: "ai", reason: "", points: [{ say: n, ask: "" }] });
  cache.set("a", ai("a"));
  cache.set("b", ai("b"));
  assert.equal(cache.get("a").points[0].say, "a");
  cache.set("c", ai("c"));
  assert.equal(cache.get("a"), undefined);
  assert.equal(cache.size(), 2);
  cache.set("d", { source: "greeting", reason: "limit", points: [] });
  assert.equal(cache.get("d"), undefined);
  assert.equal(cache.size(), 2);
});
