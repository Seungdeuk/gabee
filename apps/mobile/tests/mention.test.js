// 가족 채팅방 @가비: 부르는 글 판별, 앞 대화 정리, 내 화면 항목 끼워 넣기, 서버 호출 모양을 시험한다: npm test
import * as mention from "../src/features/family-chat/mention.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import {
  ASSISTANT_NAME,
  EMPTY_QUESTION_HINT,
  LOCAL_ASSISTANT_ID,
  MENTION,
  MENTION_EXAMPLES,
  makeNote,
  mentionHintsVisible,
  mentionHistory,
  mergeNotes,
  parseMention,
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

test("서버에 보내는 앞 대화는 최근 6턴, 15분 안의 것만이다(private 표시는 더 이상 붙지 않는다)", () => {
  const now = 1_000_000_000_000;
  const turn = (role, text, at, extra = {}) => ({ role, text, at, ...extra });
  const old = turn("user", "옛날 질문", now - 16 * 60 * 1000);
  const thread = [
    old,
    turn("user", "용돈 알려줘", now - 60_000),
    turn("assistant", "잔액은 0원이에요", now - 59_000, { private: true }), // 옛 값이 남아 있어도 서버에 보내지 않는다
    turn("user", "이번 달 지출", now - 30_000),
    turn("assistant", "총 22만원이에요", now - 29_000),
  ];
  assert.deepEqual(mentionHistory(thread, now), [
    { role: "user", text: "용돈 알려줘" },
    { role: "assistant", text: "잔액은 0원이에요" },
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

test("내 화면에만 보이는 가비 항목은 실제 사용자가 아닌 보낸 사람으로 표시한다", () => {
  const note = makeNote({ id: "n1", state: "reply", text: "답", question: "아빠 어디야?", createdAt: "2026-10-27T03:00:00Z" });
  assert.equal(note.localNote, true);
  assert.equal(note.user_id, LOCAL_ASSISTANT_ID);
  assert.equal(note.user_name, ASSISTANT_NAME);
  assert.equal(note.created_at, "2026-10-27T03:00:00Z");
});

test("내 화면 항목(확인 카드·안내)은 메시지 사이에 시간순으로 끼고, 원래 목록은 바뀌지 않는다", () => {
  const messages = [
    { id: 1, user_id: "me", created_at: "2026-10-27T03:00:00Z", text: "@가비 용돈" },
    { id: 2, user_id: "other", created_at: "2026-10-27T03:00:10Z", text: "점심 뭐 먹지" },
    { id: 3, user_id: "me", created_at: "2026-10-27T03:00:30Z", text: "국수" },
  ];
  const note = makeNote({ id: "n1", state: "cards", createdAt: "2026-10-27T03:00:20Z" });
  const merged = mergeNotes(messages, [note]);
  assert.deepEqual(merged.map((m) => m.id), [1, 2, "n1", 3]);
  assert.equal(messages.length, 3);
  assert.equal(mergeNotes(messages, []), messages); // 항목이 없으면 같은 목록을 그대로 쓴다
  const late = makeNote({ id: "n2", state: "info", createdAt: "2026-10-27T04:00:00Z" });
  assert.deepEqual(mergeNotes(messages, [late]).map((m) => m.id), [1, 2, 3, "n2"]);
});

test("mentionHintsVisible: @ 입력 중이거나 질문이 비어 있을 때만 예시를 보인다", () => {
  for (const t of ["@", "@가", "@가비", "@가비 ", "  @가비  ", " @ ", "@ㄱ", "@갑", "@각", "@깋", "@가ㅂ", "@가비\n", "@가비,", "@가비 \n"]) assert.equal(mentionHintsVisible(t), true, JSON.stringify(t));
  for (const t of ["", "가비", "@가비 이번", "@가비 이번 달 지출", "@가비야", "@가비야 ", "안녕 @가비", "@나", "@가비가", "@깍", "@ㅂ", "＠가비", "＠", "@가비비"]) assert.equal(mentionHintsVisible(t), false, JSON.stringify(t));
  for (const t of ["@", "@가비", "@가비 ", "@갑"]) assert.equal(mentionHintsVisible(t, true), true, t); // 1:1 방에서도 가족 전체방과 같다
  assert.equal(mentionHintsVisible(undefined), false);
});

test("MENTION_EXAMPLES: 가비를 부르는 예시 문장", () => {
  assert.equal(MENTION_EXAMPLES.length, 6);
  assert.equal(new Set(MENTION_EXAMPLES.map((e) => e.key)).size, MENTION_EXAMPLES.length);
  for (const e of MENTION_EXAMPLES) {
    assert.ok(e.category.trim());
    assert.ok(e.text.startsWith("@가비 "), e.text);
    const p = parseMention(e.text);
    assert.equal(p.mentioned, true);
    assert.ok(p.question.length > 0, e.text);
    assert.equal(mentionHintsVisible(e.text), false); // 채운 뒤에는 목록이 사라진다
  }
  assert.ok(EMPTY_QUESTION_HINT.includes(MENTION_EXAMPLES[0].text));
});

test("안내 문구", () => {
  assert.match(EMPTY_QUESTION_HINT, /@가비/);
  assert.equal("DIRECT_NOT_ALLOWED" in mention, false); // 1:1 에서 막는 안내는 없앴다
});

test("askAssistantInRoom: audience 를 room 으로 보내고, 방에 저장된 답의 id 와 확인 카드를 돌려준다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: JSON.parse(init.body) });
    return json(200, { reply: "이번 달 지출은 22만원이에요", source: "ai", visibility: "room", private_reasons: [], posted_message_id: 41 });
  };
  const shared = await api.askAssistantInRoom("이번 달 지출", [{ role: "user", text: "안녕" }]);
  assert.equal(calls[0].url, "http://api.test/ai-assistant/chat");
  assert.deepEqual(calls[0].body, { message: "이번 달 지출", audience: "room", history: [{ role: "user", text: "안녕" }] });
  assert.deepEqual(shared, { reply: "이번 달 지출은 22만원이에요", postedMessageId: 41, confirmCards: [] });
});

test("askAssistantInRoom: 앞 대화는 10개까지만 보내고 private 표시는 보내지 않으며, 저장되지 않은 답(구 서버)은 id 가 null 이다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  let sent;
  globalThis.fetch = async (url, init = {}) => {
    sent = JSON.parse(init.body);
    return json(200, { reply: "답", visibility: "private", private_reasons: ["자녀 용돈 장부"], posted_message_id: null });
  };
  const history = Array.from({ length: 14 }, (_, i) => ({ role: "user", text: `t${i}`, private: true }));
  const res = await api.askAssistantInRoom("q", history);
  assert.equal(sent.history.length, 10);
  assert.equal(sent.history[0].text, "t4");
  assert.ok(sent.history.every((h) => !("private" in h)));
  assert.deepEqual(res, { reply: "답", postedMessageId: null, confirmCards: [] });
});

test("askAssistantInRoom: 서버 오류는 그대로 던져 화면이 안내 문장으로 바꾼다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  globalThis.fetch = async () => json(403, { code: "ai_not_enabled", message: "m" });
  await assert.rejects(() => api.askAssistantInRoom("q"), (e) => e.code === "ai_not_enabled");
});

test("askAssistantInRoom: 1:1 방이면 room_id 를 싣고, 가족 전체방 요청은 이전과 같은 본문이다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push(JSON.parse(init.body));
    return json(200, { reply: "답", source: "ai", visibility: "room", private_reasons: [], posted_message_id: 7 });
  };
  await api.askAssistantInRoom("질문", [], "room-1");
  await api.askAssistantInRoom("질문", []);
  assert.deepEqual(calls[0], { message: "질문", audience: "room", history: [], room_id: "room-1" });
  assert.deepEqual(calls[1], { message: "질문", audience: "room", history: [] });
});

test("ChatRoomScreen: 1:1 방에서도 @가비 를 부르고 방 id 를 넘긴다(소스 확인)", () => {
  const screen = readFileSync(new URL("../src/features/family-chat/screens/ChatRoomScreen.js", import.meta.url), "utf8");
  assert.doesNotMatch(screen, /DIRECT_NOT_ALLOWED/);
  assert.doesNotMatch(screen, /const called = direct \?/);
  assert.match(screen, /useMention\(roomId \?\? undefined\)/);
  const hook = readFileSync(new URL("../src/features/family-chat/useMention.js", import.meta.url), "utf8");
  assert.match(hook, /askAssistantInRoom\(q, mentionHistory\(thread\.current\), roomId\)/);
});

const T0 = Date.parse("2026-11-05T10:00:00Z");
const iso = (min) => new Date(T0 + min * 60000).toISOString();
const msg = (id, uid, text, min, extra = {}) => ({ id, user_id: uid, text, created_at: iso(min), is_assistant: false, ...extra });
const gabi = (id, text, min) => msg(id, "gabee-assistant", text, min, { is_assistant: true });

test("restoreThread: 내 @가비 질문과 바로 뒤의 가비 답을 이전 대화로 되살린다", () => {
  const thread = mention.restoreThread(
    [msg(1, "me", "점심 뭐 먹지", 0), msg(2, "me", "@가비 이번 달 지출", 1), gabi(3, "총 22만원이에요", 1.5)],
    "me",
  );
  assert.deepEqual(
    mentionHistory(thread, T0 + 2 * 60000),
    [
      { role: "user", text: "이번 달 지출" },
      { role: "assistant", text: "총 22만원이에요" },
    ],
  );
});

test("restoreThread: 다른 사람의 @가비 질문, 사이에 다른 글이 낀 짝, 지운 글·임시 글은 되살리지 않는다", () => {
  const thread = mention.restoreThread(
    [
      msg(1, "dad", "@가비 아빠 질문", 0),
      gabi(2, "아빠에게 한 답", 0.5),
      msg(3, "me", "@가비 끼어든 질문", 1),
      msg(4, "mom", "엄마가 끼어든 글", 1.2),
      gabi(5, "누구 답인지 알 수 없는 답", 1.5),
      msg(6, "me", "@가비 지운 질문", 2, { deleted: true }),
      gabi(7, "지운 질문의 답", 2.5),
      msg(8, "me", "@가비 보내는 중", 3, { clientId: "tmp-1" }),
    ],
    "me",
  );
  assert.deepEqual(thread, []);
});

test("restoreThread: 시각은 가비 답의 시각이라 15분이 지나면 mentionHistory 가 버리고, 최근 6개까지만 보낸다", () => {
  const rows = [];
  for (let i = 0; i < 5; i++) rows.push(msg(i * 2 + 1, "me", `@가비 질문${i}`, i), gabi(i * 2 + 2, `답${i}`, i + 0.5));
  const thread = mention.restoreThread(rows, "me");
  assert.equal(thread.length, 10);
  const sent = mentionHistory(thread, T0 + 5 * 60000);
  assert.equal(sent.length, 6);
  assert.deepEqual(sent.at(-1), { role: "assistant", text: "답4" });
  assert.deepEqual(mentionHistory(thread, T0 + 40 * 60000), []);
});

test("restoreThread: @가비 만 있고 질문이 비어 있으면 건너뛴다", () => {
  assert.deepEqual(mention.restoreThread([msg(1, "me", "@가비", 0), gabi(2, "무엇을 도와드릴까요", 0.5)], "me"), []);
});

test("ChatRoomScreen: 방에 들어올 때 저장된 메시지로 이전 대화를 한 번 되살린다(소스 확인)", () => {
  const screen = readFileSync(new URL("../src/features/family-chat/screens/ChatRoomScreen.js", import.meta.url), "utf8");
  assert.match(screen, /seedThread\(restoreThread\(chat\.messages, info\.me\.id\)\)/);
  assert.match(screen, /const seedThread = mention\.seed;/);
  const hook = readFileSync(new URL("../src/features/family-chat/useMention.js", import.meta.url), "utf8");
  assert.match(hook, /const seed = useCallback/);
});

test("restoreThread: 여러 사람이 동시에 부르면 짝이 뒤바뀔 수 있어 되살리지 않는다", () => {
  const thread = mention.restoreThread(
    [msg(1, "dad", "@가비 X", 0), msg(2, "me", "@가비 Y", 0.2), gabi(3, "X 에 대한 답", 0.5), gabi(4, "Y 에 대한 답", 0.6)],
    "me",
  );
  assert.deepEqual(thread, []);
  const ok = mention.restoreThread(
    [msg(1, "dad", "@가비 X", 0), gabi(2, "X 답", 0.2), msg(3, "me", "@가비 Y", 1), gabi(4, "Y 답", 1.2)],
    "me",
  );
  assert.deepEqual(ok.map((t) => t.text), ["Y", "Y 답"]);
});

test("restoreThread: 질문과 답의 시각 차이가 2분을 넘으면 같은 짝으로 보지 않는다", () => {
  assert.deepEqual(mention.restoreThread([msg(1, "me", "@가비 Y", 0), gabi(2, "한참 뒤의 가비 글", 5)], "me"), []);
});

test("ChatRoomScreen: 방 목록이 준비되고 최근 구간일 때만 되살린다(소스 확인)", () => {
  const screen = readFileSync(new URL("../src/features/family-chat/screens/ChatRoomScreen.js", import.meta.url), "utf8");
  assert.match(screen, /chat\.status !== "ready" \|\| chat\.focusing/);
});
