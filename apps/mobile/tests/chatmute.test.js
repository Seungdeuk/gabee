// 방별 알림 끄기(mute) 순수 함수와 API 경로·메서드·본문·오류를 가짜 서버로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { roomErrorMessage } from "../src/features/family-chat/chatUtils.js";
import { buildRoomRows, MUTE_FAILED_NOTICE, muteActionLabel, mutedTitle, roomA11yLabel, roomMutedById, totalUnread, withRoomMuted } from "../src/features/family-chat/listUtils.js";
import { buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";

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
const group = { name: "우리 가족", my_id: "me", members: [{ id: "me", name: "나" }, { id: "u2", name: "엄마" }] };
const preview = () => "안녕";
const label = () => "10:00";

test("buildRoomRows: muted 는 true 일 때만 true(없으면 false), 접근성 제목에 알림 꺼짐을 덧붙인다", () => {
  const rows = buildRoomRows(
    [
      { id: "f", kind: "family", peer_user_id: null, last_message: null, unread: 3, muted: true },
      { id: "d", kind: "direct", peer_user_id: "u2", last_message: null, unread: 0 },
      { id: "d2", kind: "direct", peer_user_id: "u2", last_message: null, unread: 0, muted: "yes" },
    ],
    group,
    preview,
    label,
  );
  assert.deepEqual(rows.map((r) => r.muted), [true, false, false]);
  assert.equal(rows[0].a11yTitle, "가족 채팅방, 알림 꺼짐");
  assert.equal(rows[1].a11yTitle, "엄마님과 1:1 대화");
  assert.equal(rows[0].unread, 3); // 읽지 않음 숫자는 그대로
  assert.equal(totalUnread(rows), 3);
  assert.match(roomA11yLabel("안녕", 3, rows[0].a11yTitle), /알림 꺼짐, 안 읽은 메시지 3개/);
});

test("mutedTitle/muteActionLabel: 상태에 맞는 글자", () => {
  assert.equal(mutedTitle("가족 채팅방", false), "가족 채팅방");
  assert.equal(mutedTitle("가족 채팅방", true), "가족 채팅방, 알림 꺼짐");
  assert.equal(muteActionLabel(false), "알림 끄기");
  assert.equal(muteActionLabel(true), "알림 켜기");
});

test("withRoomMuted: 한 방만 바꾸고 제목도 맞추며, 되돌려도 제목이 겹치지 않는다", () => {
  const rows = buildRoomRows([{ id: "f", kind: "family", last_message: null, unread: 0 }, { id: "d", kind: "direct", peer_user_id: "u2", last_message: null, unread: 0 }], group, preview, label);
  const off = withRoomMuted(rows, "f", true);
  assert.equal(off[0].muted, true);
  assert.equal(off[0].a11yTitle, "가족 채팅방, 알림 꺼짐");
  assert.equal(off[1], rows[1]);
  const on = withRoomMuted(withRoomMuted(off, "f", true), "f", false);
  assert.equal(on[0].muted, false);
  assert.equal(on[0].a11yTitle, "가족 채팅방");
  assert.deepEqual(withRoomMuted(rows, "none", true), rows);
  assert.deepEqual(withRoomMuted(null, "f", true), []);
});

test("roomMutedById: 방을 모르면 null, 필드가 없으면 false", () => {
  const rooms = [{ id: "a", muted: true }, { id: "b" }];
  assert.equal(roomMutedById(rooms, "a"), true);
  assert.equal(roomMutedById(rooms, "b"), false);
  assert.equal(roomMutedById(rooms, "x"), null);
  assert.equal(roomMutedById(rooms, null), null);
  assert.equal(roomMutedById(undefined, "a"), null);
});

test("서랍 알림 행: 스위치 값·비활성·누르면 바뀔 값", () => {
  const find = (muted) => buildDrawerSections({ direct: false, muted }).flatMap((s) => s.rows).find((r) => r.key === "notifications");
  const unknown = find(null);
  assert.equal(unknown.kind, "switch");
  assert.equal(unknown.title, "이 방 알림");
  assert.equal(unknown.disabled, true);
  assert.deepEqual(resolveRowAction(unknown), { type: "none" });
  const on = find(false); // 알림 켜짐 → 누르면 끈다
  assert.deepEqual([on.value, on.disabled], [true, false]);
  assert.deepEqual(resolveRowAction(on), { type: "mute", muted: true });
  const off = find(true);
  assert.equal(off.value, false);
  assert.deepEqual(resolveRowAction(off), { type: "mute", muted: false });
});

test("API setRoomMuted: PUT, 방 id 인코딩, 본문 {muted}, 응답 그대로", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method, body: init.body });
    return json(200, { room_id: "r 1/x", muted: true });
  };
  const api = await import("../src/features/family-chat/api.js");
  const res = await api.setRoomMuted("r 1/x", true);
  assert.deepEqual(res, { room_id: "r 1/x", muted: true });
  assert.equal(calls[0].method, "PUT");
  assert.equal(calls[0].url, "http://api.test/family-chat/rooms/r%201%2Fx/mute");
  assert.deepEqual(JSON.parse(calls[0].body), { muted: true });
  await api.setRoomMuted("r", false);
  assert.deepEqual(JSON.parse(calls[1].body), { muted: false });
});

test("API setRoomMuted: 오류는 던지고(낙관적 갱신을 되돌리는 쪽이 받는다), 안내 문구가 있다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  globalThis.fetch = async () => json(404, { code: "room_not_found", message: "x" });
  await assert.rejects(() => api.setRoomMuted("r", true), (e) => e.status === 404);
  globalThis.fetch = async () => json(500, { code: "server_error", message: "x" });
  await assert.rejects(() => api.setRoomMuted("r", true), (e) => e.status === 500 && roomErrorMessage(e).length > 0);
  assert.match(MUTE_FAILED_NOTICE, /알림 설정/);
});
