// "여기까지 읽었습니다" 구분선: 위치 규칙과 buildItems 끼우기 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { buildItems, unreadDividerId } from "../src/features/family-chat/chatUtils.js";

const at = (d, h = 9) => new Date(Date.UTC(2026, 9, d, h, 0, 0)).toISOString();
const msg = (id, user, day = 23, extra = {}) => ({ id, user_id: user, text: `t${id}`, created_at: at(day), ...extra });
const ME = "me";
const base = (lastRead, unread) => ({ lastRead, unread });

test("unreadDividerId: 기준보다 큰 첫 서버 메시지 앞", () => {
  const list = [msg(1, "a"), msg(2, ME), msg(3, "a"), msg(4, "b")];
  assert.equal(unreadDividerId(list, base(2, 2), ME), 3);
  assert.equal(unreadDividerId(list, base(3, 1), ME), 4);
});

test("unreadDividerId: 내가 보낸 메시지만 남았으면 없다", () => {
  const list = [msg(1, "a"), msg(2, ME), msg(3, ME)];
  assert.equal(unreadDividerId(list, base(1, 0), ME), null);
  assert.equal(unreadDividerId(list, base(1, 2), ME), null); // unread 가 있어도 목록에 남이 보낸 것이 없으면 없음
});

test("unreadDividerId: unread 0, baseline null, 모두 읽음이면 없다", () => {
  const list = [msg(1, "a"), msg(2, "b")];
  assert.equal(unreadDividerId(list, base(0, 0), ME), null);
  assert.equal(unreadDividerId(list, null, ME), null);
  assert.equal(unreadDividerId(list, undefined, ME), null);
  assert.equal(unreadDividerId(list, base(2, 3), ME), null); // 기준이 최신이면 앞에 둘 메시지가 없다
});

test("unreadDividerId: 기준이 목록 밖(너무 오래됨)이면 가장 오래된 메시지 앞(맨 위)", () => {
  const list = [msg(101, "a"), msg(102, "b"), msg(103, "a")];
  assert.equal(unreadDividerId(list, base(10, 80), ME), 101);
});

test("unreadDividerId: 임시·실패·가비 개인 답은 무시하고 삭제된 메시지는 센다", () => {
  const list = [
    msg(1, "a"),
    msg(2, "a", 23, { deleted: true }),
    msg(3, ME),
    { id: "tmp", clientId: "c1", status: "sending", user_id: "a", text: "x", created_at: at(23) },
    { id: "failed-1", clientId: "c2", status: "failed", user_id: "b", text: "y", created_at: at(23) },
    { id: "note", localNote: true, user_id: "gabee", created_at: at(23) },
  ];
  assert.equal(unreadDividerId(list, base(1, 1), ME), 2); // 삭제된 메시지도 서버 메시지
  const onlyTemps = [msg(1, "a"), msg(2, ME), list[3], list[4], list[5]];
  assert.equal(unreadDividerId(onlyTemps, base(1, 1), ME), null); // 임시·가비만 남인 경우
});

test("buildItems: 구분선은 해당 메시지 바로 앞, 새 메시지가 와도 같은 자리", () => {
  const list = [msg(1, "a"), msg(2, "b"), msg(3, "a")];
  const items = buildItems(list, { dividerBeforeId: 2 });
  assert.deepEqual(items.map((i) => i.type), ["day", "message", "unread", "message", "message"]);
  assert.equal(items[2].key, "unread-divider");
  const more = buildItems([...list, msg(4, "b")], { dividerBeforeId: 2 });
  assert.equal(more.findIndex((i) => i.type === "unread"), 2);
});

test("buildItems: 구분선이 없으면 이전과 같다", () => {
  const list = [msg(1, "a"), msg(2, "b")];
  assert.deepEqual(buildItems(list), buildItems(list, { dividerBeforeId: null }));
  assert.ok(!buildItems(list).some((i) => i.type === "unread"));
  assert.ok(!buildItems(list, { dividerBeforeId: 99 }).some((i) => i.type === "unread"));
});

test("buildItems: 날짜가 바뀌는 지점에서는 날짜 줄 다음에 구분선", () => {
  const list = [msg(1, "a", 22), msg(2, "b", 23), msg(3, "a", 23)];
  const items = buildItems(list, { dividerBeforeId: 2 });
  assert.deepEqual(items.map((i) => i.type), ["day", "message", "day", "unread", "message", "message"]);
});

test("buildItems: 맨 위에 두면 첫 날짜 줄 다음", () => {
  const items = buildItems([msg(101, "a"), msg(102, "b")], { dividerBeforeId: 101 });
  assert.deepEqual(items.map((i) => i.type), ["day", "unread", "message", "message"]);
});

test("unreadDividerId: myId 가 없으면 모든 메시지를 남의 것으로 본다", () => {
  assert.equal(unreadDividerId([msg(1, "a"), msg(2, ME)], base(1, 1), null), 2);
  assert.equal(unreadDividerId([msg(1, "a"), msg(2, ME)], base(1, 1), undefined), 2);
});

test("unreadDividerId: lastRead 와 id 가 같은 메시지는 읽은 것", () => {
  const list = [msg(1, "a"), msg(2, "b"), msg(3, "a")];
  assert.equal(unreadDividerId(list, base(2, 1), ME), 3);
  assert.equal(unreadDividerId(list, base(3, 1), ME), null);
});

test("가비 개인 답이 구분선 자리 앞에 끼어도 구분선은 chat.messages 기준", () => {
  const list = [msg(1, "a"), msg(2, "b")];
  const note = { id: "note-1", localNote: true, user_id: "gabee", created_at: at(23, 9) };
  const id = unreadDividerId(list, base(1, 1), ME);
  assert.equal(id, 2);
  const items = buildItems([list[0], note, list[1]], { dividerBeforeId: id });
  assert.deepEqual(items.map((i) => i.type), ["day", "message", "message", "unread", "message"]);
  assert.equal(unreadDividerId([...list, note], base(1, 1), ME), 2);
});

test("buildItems: 구분선 바로 아래 메시지는 앞과 같은 사람이어도 이름을 다시 보인다", () => {
  const list = [msg(1, "a"), msg(2, "a"), msg(3, "a")];
  const names = (items) => items.filter((i) => i.type === "message").map((i) => i.showName);
  assert.deepEqual(names(buildItems(list)), [true, false, false]);
  assert.deepEqual(names(buildItems(list, { dividerBeforeId: 2 })), [true, true, false]);
});
