// 메시지 메뉴·더블탭 하트·삭제 표시·답장 순수 함수와 API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { previewText } from "../src/features/family-chat/chatUtils.js";
import {
  DELETED_TEXT,
  DOUBLE_TAP_MS,
  HEART,
  REACTIONS,
  REFRESH_EVERY_TICKS,
  canOpenMenu,
  isDoubleTap,
  markDeleted,
  markRepliesDeleted,
  menuKeys,
  menuPosition,
  messageActionError,
  myReaction,
  reactionAction,
  reactionLabel,
  refreshDue,
  refreshExisting,
  replyLine,
  replyPreview,
  sortReactions,
  withMyReaction,
} from "../src/features/family-chat/messageActions.js";

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
const msg = (id, extra = {}) => ({ id, user_id: "u1", user_name: "지민", text: `글 ${id}`, created_at: "2026-10-29T01:00:00Z", reactions: [], deleted: false, ...extra });

test("REACTIONS: 서버 허용 이모지 6개와 같고 첫 번째가 하트", () => {
  assert.equal(REACTIONS.length, 6);
  assert.deepEqual(REACTIONS.map((r) => r.emoji), ["❤️", "👍", "😂", "😮", "😢", "🙏"]);
  assert.equal(HEART, "❤️");
});

test("canOpenMenu: 서버에 저장되고 지우지 않은 메시지만", () => {
  assert.equal(canOpenMenu(msg(5)), true);
  assert.equal(canOpenMenu(msg(5, { deleted: true })), false);
  assert.equal(canOpenMenu({ ...msg(5), clientId: "tmp-1" }), false);
  assert.equal(canOpenMenu({ ...msg(5), status: "sending" }), false);
  assert.equal(canOpenMenu(null), false);
});

test("menuKeys: 반응·답장은 항상, 공지·복사는 글자가 있을 때, 삭제는 내가 보낸 것만", () => {
  assert.deepEqual(menuKeys({ message: msg(1), myId: "u1" }), ["reactions", "reply", "pin", "copy", "delete"]);
  assert.deepEqual(menuKeys({ message: msg(1), myId: "u2" }), ["reactions", "reply", "pin", "copy"]);
  assert.deepEqual(menuKeys({ message: msg(1), myId: "u1", pinned: true }), ["reactions", "reply", "unpin", "copy", "delete"]);
  // 사진: 글자가 없으면 공지·복사 없음, 글자가 있어도 공지는 텍스트만이라 없음
  assert.deepEqual(menuKeys({ message: msg(2, { text: "", attachment: { id: "a" } }), myId: "u1" }), ["reactions", "reply", "delete"]);
  assert.deepEqual(menuKeys({ message: msg(2, { text: "설명", attachment: { id: "a" } }), myId: "u2" }), ["reactions", "reply", "copy"]);
  // 가비의 답은 지울 수 없다
  assert.equal(menuKeys({ message: msg(3, { is_assistant: true, user_id: "gabee-assistant" }), myId: "gabee-assistant" }).includes("delete"), false);
  assert.deepEqual(menuKeys({ message: msg(4, { deleted: true }), myId: "u1" }), []);
});

test("withMyReaction: 처음 누르기·바꾸기·취소, 남의 반응과 정렬은 유지", () => {
  let m = msg(1, { reactions: [{ emoji: "👍", count: 2, mine: false }] });
  m = withMyReaction(m, HEART);
  assert.deepEqual(m.reactions, [{ emoji: "👍", count: 2, mine: false }, { emoji: HEART, count: 1, mine: true }]);
  m = withMyReaction(m, "👍"); // 바꾸기: 하트는 0명이라 사라지고 👍 는 3명
  assert.deepEqual(m.reactions, [{ emoji: "👍", count: 3, mine: true }]);
  m = withMyReaction(m, null); // 취소
  assert.deepEqual(m.reactions, [{ emoji: "👍", count: 2, mine: false }]);
  assert.equal(myReaction(m), null);
  assert.equal(myReaction(withMyReaction(m, "🙏")), "🙏");
  // 원본은 바꾸지 않는다
  assert.deepEqual(msg(1).reactions, []);
  const shared = { emoji: "👍", count: 2, mine: false };
  const source = msg(1, { reactions: [shared] });
  withMyReaction(source, "👍");
  assert.deepEqual(shared, { emoji: "👍", count: 2, mine: false }); // 반응 객체도 바뀌지 않는다
});

test("markRepliesDeleted: 지운 메시지를 인용한 답장만 삭제 표시로, 바뀐 것이 없으면 같은 배열", () => {
  const quoted = msg(2, { reply_to: { id: 1, user_name: "지민", text: "원본", deleted: false, has_attachment: true } });
  const other = msg(3, { reply_to: { id: 9, user_name: "수진", text: "다른 글", deleted: false, has_attachment: false } });
  const list = [msg(1), quoted, other];
  const next = markRepliesDeleted(list, 1);
  assert.deepEqual(next[1].reply_to, { id: 1, user_name: "지민", text: "", deleted: true, has_attachment: false });
  assert.equal(next[2], other);
  assert.equal(markRepliesDeleted(next, 1), next);
});

test("sortReactions: 많은 순, 같으면 허용 목록 순서", () => {
  const out = sortReactions([
    { emoji: "🙏", count: 1, mine: false },
    { emoji: HEART, count: 1, mine: false },
    { emoji: "👍", count: 2, mine: false },
  ]);
  assert.deepEqual(out.map((r) => r.emoji), ["👍", HEART, "🙏"]);
});

test("reactionAction: 같은 이모지를 다시 누르면 취소, 다르면 정한다(더블탭 하트도 같다)", () => {
  assert.deepEqual(reactionAction(msg(1), HEART), { type: "set", emoji: HEART });
  const hearted = withMyReaction(msg(1), HEART);
  assert.deepEqual(reactionAction(hearted, HEART), { type: "remove", emoji: HEART });
  assert.deepEqual(reactionAction(hearted, "👍"), { type: "set", emoji: "👍" });
});

test("markDeleted: 글자·사진·반응·답장 표시를 비우고 원본은 그대로", () => {
  const original = msg(1, { attachment: { id: "a" }, reactions: [{ emoji: HEART, count: 1, mine: true }], reply_to: { id: 9 } });
  const gone = markDeleted(original);
  assert.deepEqual([gone.deleted, gone.text, gone.attachment, gone.reactions, gone.reply_to], [true, "", null, [], null]);
  assert.equal(original.deleted, false);
  assert.equal(original.text, "글 1");
});

test("replyPreview·replyLine: 40자까지, 사진·삭제 표시, 별명 우선", () => {
  const p = replyPreview(msg(7, { text: "가".repeat(100) }), (id) => (id === "u1" ? "우리 엄마" : undefined));
  assert.equal(p.text.length, 40);
  assert.equal(p.user_name, "우리 엄마");
  assert.equal(p.id, 7);
  assert.equal(replyLine(p), "가".repeat(40));
  assert.equal(replyLine(replyPreview(msg(8, { text: "", attachment: { id: "a" } }))), "사진");
  assert.equal(replyLine(replyPreview(msg(9, { deleted: true }))), DELETED_TEXT);
  assert.equal(replyLine({ id: 1, deleted: true, text: "남은 글" }), DELETED_TEXT);
  assert.equal(replyLine(null), "");
});

test("menuPosition: 누른 지점 근처, 화면 밖으로 나가지 않고 아래가 모자라면 위로", () => {
  const size = { width: 260, height: 300 };
  const screen = { width: 400, height: 800 };
  assert.deepEqual(menuPosition({ x: 200, y: 100 }, size, screen), { left: 70, top: 108 });
  assert.equal(menuPosition({ x: 10, y: 100 }, size, screen).left, 8); // 왼쪽 가장자리
  assert.equal(menuPosition({ x: 395, y: 100 }, size, screen).left, 400 - 260 - 8); // 오른쪽 가장자리
  assert.equal(menuPosition({ x: 200, y: 700 }, size, screen).top, 700 - 300 - 8); // 아래가 모자라 위로
  assert.equal(menuPosition({ x: 200, y: 50 }, { width: 260, height: 900 }, screen).top, 8); // 너무 커도 위쪽 여백 안
});

test("isDoubleTap·refreshDue: 간격과 틱 수 판정", () => {
  assert.equal(isDoubleTap(null, 1000), false);
  assert.equal(isDoubleTap(1000, 1000 + DOUBLE_TAP_MS), true);
  assert.equal(isDoubleTap(1000, 1000 + DOUBLE_TAP_MS + 1), false);
  assert.equal(refreshDue(REFRESH_EVERY_TICKS - 1), false);
  assert.equal(refreshDue(REFRESH_EVERY_TICKS), true);
});

test("refreshExisting: 이미 가진 메시지의 반응·삭제만 갱신하고 새 메시지는 넣지 않으며 임시는 그대로", () => {
  const existing = [msg(1), msg(2, { reactions: [{ emoji: "👍", count: 1, mine: false }] }), { ...msg("tmp-1"), clientId: "tmp-1", status: "sending" }];
  const incoming = [
    msg(2, { reactions: [{ emoji: "👍", count: 2, mine: true }] }), // 반응이 늘었다
    msg(1, { deleted: true, text: "" }), // 상대가 지웠다
    msg(3), // 목록에 없는 새 메시지는 폴링 몫이다
  ];
  const next = refreshExisting(existing, incoming);
  assert.deepEqual(next.map((m) => m.id), [1, 2, "tmp-1"]);
  assert.equal(next[0].deleted, true);
  assert.equal(next[1].reactions[0].count, 2);
  assert.equal(next[2], existing[2]);
  // 바뀐 것이 없으면 같은 배열(불필요한 다시 그리기 방지)
  assert.equal(refreshExisting(next, incoming), next);
});

test("previewText: 지운 메시지는 삭제 문구, 사진은 사진, 내 글은 앞에 나:", () => {
  assert.equal(previewText(msg(1, { deleted: true, text: "" }), "u1"), "삭제된 메시지입니다");
  assert.equal(previewText(msg(1, { text: "", attachment: { id: "a" } }), "u2"), "사진");
  assert.equal(previewText(msg(1), "u1"), "나: 글 1");
});

test("messageActionError: 삭제·반응·답장 오류 문구에 메시지 글자를 넣지 않는다", () => {
  assert.equal(messageActionError({ status: 400, code: "message_deleted" }), "삭제된 메시지예요");
  assert.equal(messageActionError({ status: 400, code: "reply_deleted" }, "reply"), "삭제된 메시지예요");
  assert.equal(messageActionError({ status: 400, code: "invalid_reaction" }), "쓸 수 없는 반응이에요");
  assert.equal(messageActionError({ status: 403 }, "delete"), "내가 보낸 메시지만 삭제할 수 있어요");
  assert.equal(messageActionError({ status: 404 }), "메시지를 찾을 수 없어요");
  assert.equal(messageActionError({ status: 429 }), "너무 자주 눌렀어요. 잠시 뒤에 다시 해 주세요");
  assert.equal(messageActionError({ status: 500 }, "delete"), "삭제하지 못했어요. 다시 시도해 주세요");
  assert.equal(messageActionError({ status: 500 }), "반응을 남기지 못했어요. 다시 시도해 주세요");
});

test("reactionLabel: 이름·사람 수·내가 눌렀는지", () => {
  assert.match(reactionLabel({ emoji: HEART, count: 2, mine: true }), /^하트 2명, 내가 누름/);
  assert.match(reactionLabel({ emoji: "👍", count: 1, mine: false }), /^좋아요 1명, 누르면 나도 눌러요/);
});

test("API: deleteMessage·reactToMessage·removeReaction·sendMessage(replyToId) 경로·메서드·본문", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null });
    return json(200, { id: 5, text: "", reactions: [], deleted: true });
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.deleteMessage({ messageId: 5 });
  await api.deleteMessage({ roomId: "r1", messageId: 6 });
  await api.reactToMessage({ messageId: 5, emoji: "👍" });
  await api.reactToMessage({ roomId: "r1", messageId: 5, emoji: HEART });
  await api.removeReaction({ messageId: 5 });
  await api.removeReaction({ roomId: "r1", messageId: 5 });
  await api.sendMessage("답장", null, 5);
  await api.sendMessage("답장", "r1", 5);
  await api.sendMessage("그냥", null);
  const [d1, d2, r1, r2, x1, x2, s1, s2, s3] = calls;
  assert.deepEqual([d1.method, d1.url.endsWith("/family-chat/messages/5")], ["DELETE", true]);
  assert.deepEqual([d2.method, d2.url.endsWith("/family-chat/messages/6?room_id=r1")], ["DELETE", true]);
  assert.deepEqual([r1.method, r1.url.endsWith("/family-chat/messages/5/reaction"), r1.body], ["PUT", true, { emoji: "👍" }]);
  assert.deepEqual([r2.url.endsWith("/family-chat/messages/5/reaction?room_id=r1"), r2.body], [true, { emoji: HEART }]);
  assert.deepEqual([x1.method, x1.url.endsWith("/family-chat/messages/5/reaction")], ["DELETE", true]);
  assert.equal(x2.url.endsWith("/family-chat/messages/5/reaction?room_id=r1"), true);
  assert.deepEqual(s1.body, { text: "답장", reply_to_id: 5 });
  assert.deepEqual(s2.body, { text: "답장", room_id: "r1", reply_to_id: 5 });
  assert.deepEqual(s3.body, { text: "그냥" }); // 답장이 아니면 reply_to_id 를 보내지 않는다
});
