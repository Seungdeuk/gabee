// 1:1 채팅방 나가기(앱): API 경로·메서드, 목록 행(상대가 나간 방), 스와이프 두 액션(알림 끄기 | 나가기), 확인창, 나간 방의 입력창 대체: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import { buildRoomRows, formatRoomTime } from "../src/features/family-chat/listUtils.js";
import { previewText } from "../src/features/family-chat/chatUtils.js";
import { chatErrorMessage } from "../src/features/family-chat/messages.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const read = (rel) => readFileSync(new URL(`../src/features/family-chat/${rel}`, import.meta.url), "utf8");
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("API leaveRoom: POST /family-chat/rooms/{id}/leave, 방 id 인코딩, 본문 없음, 204 는 null", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method, body: init.body });
    return new Response(null, { status: 204 });
  };
  const api = await import("../src/features/family-chat/api.js");
  const res = await api.leaveRoom("r 1/x");
  assert.equal(res, null);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].url, "http://api.test/family-chat/rooms/r%201%2Fx/leave");
  assert.equal(calls[0].body, undefined);
});

test("API leaveRoom: 오류는 던지고 안내 문구가 있다(상대가 나간 방에는 보낼 수 없다)", async () => {
  const api = await import("../src/features/family-chat/api.js");
  globalThis.fetch = async () => json(404, { code: "room_not_found", message: "x" });
  await assert.rejects(() => api.leaveRoom("r"), (e) => e.status === 404);
  assert.match(chatErrorMessage({ code: "peer_left_room", status: 409 }), /상대방이 나가서/);
  assert.match(chatErrorMessage({ code: "cannot_leave_family_room", status: 400 }), /가족 전체방/);
});

test("buildRoomRows: 상대가 나간 방(peer_left)은 나간 사람 이름으로 '상대방이 나갔어요'를 보이고 peerLeft 를 켠다", () => {
  const group = { my_id: "me", name: "우리 가족", members: [{ id: "me", name: "나" }, { id: "p1", name: "수진" }] };
  const rooms = [
    { id: "d1", kind: "direct", peer_user_id: "p1", peer_left: true, last_message: { id: 5, user_id: "p1", user_name: "수진", text: "안녕", created_at: "2026-11-09T00:00:00Z" }, unread: 0 },
    { id: "d2", kind: "direct", peer_user_id: "p1", last_message: null, unread: 0 },
  ];
  const [left, normal] = buildRoomRows(rooms, group, previewText, formatRoomTime);
  assert.equal(left.peerLeft, true);
  assert.equal(left.name, "수진");
  assert.equal(left.last, "상대방이 나갔어요");
  assert.equal(normal.peerLeft, false);
  assert.notEqual(normal.last, "상대방이 나갔어요");
});

test("스와이프 행: 1:1 방은 '알림 끄기 | 나가기' 두 액션, 가족 전체방은 알림 끄기만(나가기는 onLeave 가 있을 때만)", () => {
  const swipe = read("components/SwipeableRoomRow.js");
  assert.match(swipe, /export default function SwipeableRoomRow\(\{ room, onPress, onToggleMute, onLeave, divider = false \}\)/);
  assert.match(swipe, /const canLeave = room\.kind === "direct" && Boolean\(onLeave\)/);
  assert.match(swipe, /accessibilityLabel=\{LEAVE_LABEL\}/);
  assert.match(swipe, /width: canLeave \? ACTION_WIDTH \* 2 : ACTION_WIDTH/);
  assert.match(swipe, /methods\.close\(\);\s*onLeave\(\);/); // 누르면 닫고 바로 나가지 않고 확인창을 부른다
});

test("목록 화면: 나가기는 확인창을 거쳐 서버에 요청하고, 성공하면 목록에서 지우며, 나간 방은 읽기 전용으로 연다", () => {
  const screen = read("screens/FamilyChatScreen.js");
  assert.match(screen, /import \{[^}]*leaveRoom[^}]*\} from "\.\.\/api"/);
  assert.match(screen, /<ConfirmDialog[\s\S]*confirmLabel="나가기"/);
  assert.match(screen, /되돌릴 수 없/); // 둘 다 나가면 대화가 지워진다는 안내
  assert.match(screen, /onLeave=\{room\.kind === "direct" \? \(\) => askLeave\(room\) : undefined\}/);
  assert.match(screen, /peerLeft: room\.peerLeft \? "1" : ""/);
});

test("채팅방 화면: 상대가 나간 방(peerLeft)은 입력창 대신 안내를 보인다", () => {
  const room = read("screens/ChatRoomScreen.js");
  assert.match(room, /const peerLeft = params\.peerLeft === "1"/);
  assert.match(room, /peerLeft \? \([\s\S]*상대방이 나가서 메시지를 보낼 수 없어요[\s\S]*\) : \(\s*<Composer/);
});
