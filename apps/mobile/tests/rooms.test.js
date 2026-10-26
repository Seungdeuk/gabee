// 대화방(가족 전체방 + 1:1) 순수 함수와 API 경로·본문을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { previewText } from "../src/features/family-chat/chatUtils.js";
import { buildRoomRows, formatRoomTime, memberName, pickableMembers, roomA11yLabel } from "../src/features/family-chat/listUtils.js";

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
const members = [
  { id: "me", name: "지민", display_name: null, photo_url: null },
  { id: "mom", name: "엄마", display_name: "우리 엄마", photo_url: "/family-group/users/mom/photo?v=1" },
  { id: "dad", name: "아빠", display_name: null, photo_url: null },
];
const group = { id: "g1", name: "우리 가족", my_id: "me", members };
const msg = (id, user_id, text) => ({ id, user_id, user_name: "x", text, created_at: "2026-10-23T06:00:00Z" });

test("memberName: 별명(display_name) 우선, 없으면 이름, 아무것도 없으면 '가족'", () => {
  assert.equal(memberName(members[1]), "우리 엄마");
  assert.equal(memberName(members[2]), "아빠");
  assert.equal(memberName(undefined), "가족");
});

test("buildRoomRows: 가족 전체방은 가족 이름과 인원, 1:1 방은 상대 이름·사진·id", () => {
  const rooms = [
    { id: "r-family", kind: "family", peer_user_id: null, last_message: msg(5, "dad", "저녁 뭐 먹지"), unread: 2 },
    { id: "r-mom", kind: "direct", peer_user_id: "mom", last_message: msg(9, "me", "알겠어요"), unread: 0 },
  ];
  const rows = buildRoomRows(rooms, group, previewText, formatRoomTime);
  assert.equal(rows.length, 2);
  assert.deepEqual(
    { id: rows[0].id, name: rows[0].name, count: rows[0].count, unread: rows[0].unread, last: rows[0].last, peerId: rows[0].peerId },
    { id: "r-family", name: "우리 가족", count: 3, unread: 2, last: "저녁 뭐 먹지", peerId: undefined },
  );
  assert.equal(rows[0].a11yTitle, "가족 채팅방");
  assert.deepEqual(
    { id: rows[1].id, name: rows[1].name, peerId: rows[1].peerId, photoUrl: rows[1].photoUrl, last: rows[1].last, count: rows[1].count },
    { id: "r-mom", name: "우리 엄마", peerId: "mom", photoUrl: "/family-group/users/mom/photo?v=1", last: "나: 알겠어요", count: undefined },
  );
  assert.equal(rows[1].a11yTitle, "우리 엄마님과 1:1 대화");
});

test("buildRoomRows: 메시지가 없으면 안내 문구와 빈 시각, 나간 상대는 '가족', 잘못된 입력은 빈 목록", () => {
  const rows = buildRoomRows([{ id: "r1", kind: "direct", peer_user_id: "gone", last_message: null, unread: undefined }], group, previewText, formatRoomTime);
  assert.equal(rows[0].name, "나간 가족");
  assert.equal(rows[0].last, "아직 대화가 없어요");
  assert.equal(rows[0].time, "");
  assert.equal(rows[0].unread, 0);
  assert.deepEqual(buildRoomRows(null, group, previewText, formatRoomTime), []);
});

test("pickableMembers: 나를 뺀 구성원, 별명 우선", () => {
  assert.deepEqual(pickableMembers(members, "me"), [
    { id: "mom", name: "우리 엄마", photoUrl: "/family-group/users/mom/photo?v=1" },
    { id: "dad", name: "아빠", photoUrl: null },
  ]);
  assert.deepEqual(pickableMembers(undefined, "me"), []);
  assert.deepEqual(pickableMembers([{ id: "me", name: "나" }], "me"), []); // 나만 있는 가족
});

test("roomA11yLabel: 제목과 안 읽은 수를 함께 읽어 준다", () => {
  assert.equal(roomA11yLabel("안녕", 0), "가족 채팅방, 마지막 메시지 안녕");
  assert.equal(roomA11yLabel("안녕", 3, "아빠님과 1:1 대화"), "아빠님과 1:1 대화, 안 읽은 메시지 3개, 마지막 메시지 안녕");
});

test("API: room_id 가 없으면 이전 앱과 같은 요청, 있으면 쿼리/본문에 room_id 만 더한다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : undefined });
    if (String(url).includes("/rooms/direct")) return json(200, { id: "r1", kind: "direct", peer_user_id: "mom", last_message: null, unread: 0 });
    if (String(url).includes("/rooms")) return json(200, []);
    if (String(url).includes("/read-states")) return json(200, []);
    if (String(url).includes("/unread")) return json(200, { unread: 0, last_read_message_id: 0 });
    if (String(url).includes("/read")) return json(200, { last_read_message_id: 4 });
    if (init.method === "POST") return json(201, msg(1, "me", "hi"));
    return json(200, []);
  };
  const api = await import("../src/features/family-chat/api.js");

  await api.listMessages({ latest: true, limit: 50 });
  await api.listMessages({ afterId: 7, limit: 100, roomId: "r 1" });
  await api.sendMessage("안녕");
  await api.sendMessage("안녕", "r1");
  await api.markRead(4);
  await api.markRead(4, "r1");
  await api.getReadStates();
  await api.getReadStates("r1");
  await api.getUnread();
  await api.getUnread("r1");
  await api.listRooms();
  const opened = await api.openDirectRoom("mom");

  const by = (i) => calls[i];
  assert.match(by(0).url, /\/family-chat\/messages\?latest=true&limit=50$/); // room_id 없음
  assert.match(by(1).url, /after_id=7&limit=100&room_id=r%201$/); // 안전하게 인코딩
  assert.deepEqual(by(2).body, { text: "안녕" });
  assert.deepEqual(by(3).body, { text: "안녕", room_id: "r1" });
  assert.deepEqual(by(4).body, { message_id: 4 });
  assert.deepEqual(by(5).body, { message_id: 4, room_id: "r1" });
  assert.match(by(6).url, /\/family-chat\/read-states$/);
  assert.match(by(7).url, /\/family-chat\/read-states\?room_id=r1$/);
  assert.match(by(8).url, /\/family-chat\/unread$/);
  assert.match(by(9).url, /\/family-chat\/unread\?room_id=r1$/);
  assert.equal(by(10).method, "GET");
  assert.match(by(10).url, /\/family-chat\/rooms$/);
  assert.equal(by(11).method, "POST");
  assert.deepEqual(by(11).body, { user_id: "mom" });
  assert.equal(opened.id, "r1");
  // 토큰·대화 글자가 URL 에 들어가지 않는다
  for (const c of calls) assert.ok(!c.url.includes("legacy-dev-token") && !c.url.includes("안녕"), c.url);
});
