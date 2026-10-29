// 메시지 메뉴·더블탭 하트·삭제 표시·답장 순수 함수와 API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { previewText, shouldShowName, shouldShowTime } from "../src/features/family-chat/chatUtils.js";
import {
  DELETED_TEXT,
  DOUBLE_TAP_MS,
  HEART,
  REACTIONS,
  REFRESH_EVERY_TICKS,
  applyDeletedIds,
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
  assert.match(messageActionError({ status: 400, code: "reply_deleted" }, "reply"), /답장하려던 메시지가 삭제돼서 답장 없이 보낼 수 있어요/); // 답장 전용 안내(다시 보내기는 답장 없이 간다)
  assert.equal(messageActionError({ status: 400, code: "message_deleted" }), "삭제된 메시지예요");
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
  await api.listDeletedMessages({ since: "2026-10-29T01:00:00Z" });
  await api.listDeletedMessages({ roomId: "r1", since: "2026-10-29T01:00:00.123+00:00" });
  const [d1, d2, r1, r2, x1, x2, s1, s2, s3, l1, l2] = calls;
  assert.deepEqual([d1.method, d1.url.endsWith("/family-chat/messages/5")], ["DELETE", true]);
  assert.deepEqual([d2.method, d2.url.endsWith("/family-chat/messages/6?room_id=r1")], ["DELETE", true]);
  assert.deepEqual([r1.method, r1.url.endsWith("/family-chat/messages/5/reaction"), r1.body], ["PUT", true, { emoji: "👍" }]);
  assert.deepEqual([r2.url.endsWith("/family-chat/messages/5/reaction?room_id=r1"), r2.body], [true, { emoji: HEART }]);
  assert.deepEqual([x1.method, x1.url.endsWith("/family-chat/messages/5/reaction")], ["DELETE", true]);
  assert.equal(x2.url.endsWith("/family-chat/messages/5/reaction?room_id=r1"), true);
  assert.deepEqual(s1.body, { text: "답장", reply_to_id: 5 });
  assert.deepEqual(s2.body, { text: "답장", room_id: "r1", reply_to_id: 5 });
  assert.deepEqual(s3.body, { text: "그냥" }); // 답장이 아니면 reply_to_id 를 보내지 않는다
  assert.deepEqual([l1.method, l1.url.endsWith("/family-chat/messages/deleted?since=2026-10-29T01%3A00%3A00Z")], ["GET", true]);
  assert.equal(l2.url.endsWith("/family-chat/messages/deleted?since=2026-10-29T01%3A00%3A00.123%2B00%3A00&room_id=r1"), true);
});

test("applyDeletedIds: 서버가 알려 준 삭제 id 만 삭제 표시로(이미 지운 것·없는 id 는 그대로), 인용 답장도 반영", () => {
  const quoted = msg(3, { reply_to: { id: 1, user_name: "지민", text: "원본", deleted: false, has_attachment: false } });
  const list = [msg(1), msg(2, { deleted: true, text: "" }), quoted];
  const next = applyDeletedIds(list, [1, 2, 99]);
  assert.equal(next[0].deleted, true);
  assert.equal(next[0].text, "");
  assert.equal(next[1], list[1]); // 이미 지운 것은 같은 객체
  assert.equal(next[2].reply_to.deleted, true);
  assert.equal(applyDeletedIds(list, []), list); // 바뀐 것이 없으면 같은 배열
  assert.equal(applyDeletedIds(next, [1]), next);
});

test("shouldShowName·shouldShowTime: 지운 메시지가 사이에 끼면 이름·시각을 숨기지 않는다", () => {
  const a = msg(1, { user_id: "u1", created_at: "2026-10-29T01:00:10Z" });
  const gone = msg(2, { user_id: "u1", deleted: true, text: "", created_at: "2026-10-29T01:00:20Z" });
  const b = msg(3, { user_id: "u1", created_at: "2026-10-29T01:00:30Z" });
  assert.equal(shouldShowName(a, b), false); // 같은 사람이 이어서 말하면 생략(기존 규칙)
  assert.equal(shouldShowName(gone, b), true); // 앞이 지운 줄이면 누가 보냈는지 이름을 보인다
  assert.equal(shouldShowTime(a, gone), true); // 다음이 지운 줄이면 이 메시지의 시각을 보인다
  assert.equal(shouldShowTime(a, b), false); // 같은 분 이어서 보내면 마지막에만(기존 규칙)
});

test("menuPosition: 말풍선 위치를 알면 그 바로 아래에 붙이고(내 말풍선은 오른쪽 끝, 상대는 왼쪽 끝), 아래가 모자라면 위로", () => {
  const size = { width: 196, height: 160 };
  const screen = { width: 400, height: 800 };
  const rect = { x: 250, y: 300, width: 140, height: 40 };
  const mine = menuPosition({ x: 320, y: 340, rect, side: "right" }, size, screen);
  assert.equal(mine.left, 250 + 140 - 196); // 말풍선 오른쪽 끝에 맞춤
  assert.ok(mine.top >= 340 && mine.top <= 348); // 말풍선 아래
  const other = menuPosition({ x: 60, y: 140, rect: { x: 56, y: 100, width: 120, height: 40 }, side: "left" }, size, screen);
  assert.equal(other.left, 56); // 말풍선 왼쪽 끝에 맞춤
  const bottom = menuPosition({ x: 100, y: 780, rect: { x: 56, y: 740, width: 120, height: 40 }, side: "left" }, size, screen);
  assert.equal(bottom.top, 740 - 160 - 4); // 아래가 모자라 말풍선 위로
  // 화면 가장자리 밖으로 나가지 않는다
  assert.equal(menuPosition({ x: 5, y: 100, rect: { x: 0, y: 100, width: 40, height: 40 }, side: "right" }, size, screen).left, 8);
});
