// 가족 채팅방 @가비: 부르는 글 판별, 앞 대화 정리, 개인용 답 끼워 넣기, 서버 호출 모양을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  ASSISTANT_NAME,
  DIRECT_NOT_ALLOWED,
  EMPTY_QUESTION_HINT,
  LOCAL_ASSISTANT_ID,
  MENTION,
  makeNote,
  mentionHistory,
  mergeNotes,
  parseMention,
  privateNotice,
  pushThread,
} from "../src/features/family-chat/mention.js";

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

test("@가비 로 시작하는 글만 부르는 것으로 본다", () => {
  assert.deepEqual(parseMention("@가비 이번 달 지출 알려줘"), { mentioned: true, question: "이번 달 지출 알려줘" });
  assert.deepEqual(parseMention("  @가비, 오늘 일정은?"), { mentioned: true, question: "오늘 일정은?" });
  assert.deepEqual(parseMention("@가비: 문서 요약해줘"), { mentioned: true, question: "문서 요약해줘" });
  assert.deepEqual(parseMention("@가비"), { mentioned: true, question: "" });
  assert.equal(MENTION, "@가비");
});

test("글 중간의 @가비 나 이름이 이어진 글은 부르는 것이 아니다", () => {
  assert.equal(parseMention("엄마 @가비 불러볼까").mentioned, false);
  assert.equal(parseMention("@가비야 안녕").mentioned, false);
  assert.equal(parseMention("@가비서 회의").mentioned, false);
  assert.equal(parseMention("가비 알려줘").mentioned, false);
  assert.equal(parseMention("").mentioned, false);
  assert.equal(parseMention(null).mentioned, false);
});

test("서버에 보내는 앞 대화는 최근 6턴, 15분 안의 것만이고 개인용 답에는 private 표시가 붙는다", () => {
  const now = 1_000_000_000_000;
  const turn = (role, text, at, extra = {}) => ({ role, text, at, ...extra });
  const old = turn("user", "옛날 질문", now - 16 * 60 * 1000);
  const thread = [
    old,
    turn("user", "용돈 알려줘", now - 60_000),
    turn("assistant", "잔액은 0원이에요", now - 59_000, { private: true }),
    turn("user", "이번 달 지출", now - 30_000),
    turn("assistant", "총 22만원이에요", now - 29_000),
  ];
  assert.deepEqual(mentionHistory(thread, now), [
    { role: "user", text: "용돈 알려줘" },
    { role: "assistant", text: "잔액은 0원이에요", private: true },
    { role: "user", text: "이번 달 지출" },
    { role: "assistant", text: "총 22만원이에요" },
  ]);
  const many = Array.from({ length: 10 }, (_, i) => turn("user", `질문 ${i}`, now - 1000));
  assert.deepEqual(mentionHistory(many, now).map((t) => t.text), ["질문 4", "질문 5", "질문 6", "질문 7", "질문 8", "질문 9"]);
  assert.deepEqual(mentionHistory([], now), []);
});

test("앞 대화는 아주 길어지지 않는다", () => {
  let thread = [];
  for (let i = 0; i < 30; i += 1) thread = pushThread(thread, { role: "user", text: `q${i}`, at: i });
  assert.equal(thread.length, 12);
  assert.equal(thread.at(-1).text, "q29");
});

test("개인용으로 판단된 이유를 한 줄로 안내한다", () => {
  assert.equal(privateNotice(["자녀 용돈 장부", "가족 위치"]), "개인 정보가 있어서 방에 올리지 않았어요 · 자녀 용돈 장부, 가족 위치");
  assert.equal(privateNotice([]), "개인 정보가 있어서 방에 올리지 않았어요");
  assert.equal(privateNotice(undefined), "개인 정보가 있어서 방에 올리지 않았어요");
});

test("내 화면에만 보이는 가비 항목은 실제 사용자가 아닌 보낸 사람으로 표시한다", () => {
  const note = makeNote({ id: "n1", state: "private", text: "답", reasons: ["가족 위치"], question: "아빠 어디야?", createdAt: "2026-10-27T03:00:00Z" });
  assert.equal(note.localNote, true);
  assert.equal(note.user_id, LOCAL_ASSISTANT_ID);
  assert.equal(note.user_name, ASSISTANT_NAME);
  assert.equal(note.created_at, "2026-10-27T03:00:00Z");
});

test("개인용 답은 메시지 사이에 시간순으로 끼고, 원래 목록은 바뀌지 않는다", () => {
  const messages = [
    { id: 1, user_id: "me", created_at: "2026-10-27T03:00:00Z", text: "@가비 용돈" },
    { id: 2, user_id: "other", created_at: "2026-10-27T03:00:10Z", text: "점심 뭐 먹지" },
    { id: 3, user_id: "me", created_at: "2026-10-27T03:00:30Z", text: "국수" },
  ];
  const note = makeNote({ id: "n1", state: "private", text: "답", createdAt: "2026-10-27T03:00:20Z" });
  const merged = mergeNotes(messages, [note]);
  assert.deepEqual(merged.map((m) => m.id), [1, 2, "n1", 3]);
  assert.equal(messages.length, 3);
  assert.equal(mergeNotes(messages, []), messages); // 항목이 없으면 같은 목록을 그대로 쓴다
  const late = makeNote({ id: "n2", state: "info", createdAt: "2026-10-27T04:00:00Z" });
  assert.deepEqual(mergeNotes(messages, [late]).map((m) => m.id), [1, 2, 3, "n2"]);
});

test("안내 문구", () => {
  assert.match(EMPTY_QUESTION_HINT, /@가비/);
  assert.match(DIRECT_NOT_ALLOWED, /1:1/);
});

test("askAssistantInRoom: audience 를 room 으로 보내고, 방에 올린 답과 개인용 답을 구분해 돌려준다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: JSON.parse(init.body) });
    return calls.length === 1
      ? json(200, { reply: "이번 달 지출은 22만원이에요", source: "ai", visibility: "room", private_reasons: [], posted_message_id: 41 })
      : json(200, { reply: "잔액은 0원이에요", source: "ai", visibility: "private", private_reasons: ["자녀 용돈 장부"], posted_message_id: null });
  };
  const shared = await api.askAssistantInRoom("이번 달 지출", [{ role: "user", text: "안녕" }]);
  assert.equal(calls[0].url, "http://api.test/ai-assistant/chat");
  assert.deepEqual(calls[0].body, { message: "이번 달 지출", audience: "room", history: [{ role: "user", text: "안녕" }] });
  assert.deepEqual(shared, { reply: "이번 달 지출은 22만원이에요", visibility: "room", reasons: [], postedMessageId: 41, confirmCards: [] });
  const personal = await api.askAssistantInRoom("용돈", [{ role: "assistant", text: "앞서", private: true }]);
  assert.deepEqual(calls[1].body.history, [{ role: "assistant", text: "앞서", private: true }]);
  assert.deepEqual(personal, { reply: "잔액은 0원이에요", visibility: "private", reasons: ["자녀 용돈 장부"], postedMessageId: null, confirmCards: [] });
});

test("askAssistantInRoom: 모르는 visibility 값은 개인용으로 보고(방에 올리지 않는 쪽), 앞 대화는 10개까지만 보낸다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  let sent;
  globalThis.fetch = async (url, init = {}) => {
    sent = JSON.parse(init.body);
    return json(200, { reply: "답", visibility: "something-new" });
  };
  const history = Array.from({ length: 14 }, (_, i) => ({ role: "user", text: `t${i}` }));
  const res = await api.askAssistantInRoom("q", history);
  assert.equal(sent.history.length, 10);
  assert.equal(sent.history[0].text, "t4");
  assert.equal(res.visibility, "private");
  assert.deepEqual(res.reasons, []);
  assert.equal(res.postedMessageId, null);
});

test("askAssistantInRoom: 서버 오류는 그대로 던져 화면이 안내 문장으로 바꾼다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  globalThis.fetch = async () => json(403, { code: "ai_not_enabled", message: "m" });
  await assert.rejects(() => api.askAssistantInRoom("q"), (e) => e.code === "ai_not_enabled");
});
