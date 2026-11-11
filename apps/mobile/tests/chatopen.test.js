// 소통 푸시를 눌렀을 때 열 채팅방 경로 정하기(푸시에는 방 id 만 있다): npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { chatRouteFor } from "../src/features/family-chat/chatOpen.js";

const rooms = [
  { id: "fam1", kind: "family", peer_user_id: null },
  { id: "dir1", kind: "direct", peer_user_id: "u2" },
  { id: "dir2", kind: "direct", peer_user_id: null },
];

test("chatRouteFor: 가족방은 방 인자 없이 /chat-room(roomId 를 주면 1:1 로 취급된다)", () => {
  assert.equal(chatRouteFor(rooms, "fam1"), "/chat-room");
});

test("chatRouteFor: 1:1 방은 roomId 와 상대 id(peer)를 함께 넘긴다", () => {
  assert.deepEqual(chatRouteFor(rooms, "dir1"), { pathname: "/chat-room", params: { roomId: "dir1", peer: "u2" } });
  assert.deepEqual(chatRouteFor(rooms, "dir2"), { pathname: "/chat-room", params: { roomId: "dir2", peer: "" } }); // 상대를 모르면 빈 값
});

test("chatRouteFor: 목록에 없거나 이상한 입력이면 소통 탭 목록으로", () => {
  assert.equal(chatRouteFor(rooms, "nope"), "/family-chat");
  assert.equal(chatRouteFor([], "fam1"), "/family-chat");
  assert.equal(chatRouteFor(null, "fam1"), "/family-chat");
  assert.equal(chatRouteFor(rooms, undefined), "/family-chat");
});
