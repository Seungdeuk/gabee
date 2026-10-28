// 채팅방: 순수 함수(병합·날짜 묶기·시각·폴링 간격)와 메시지 API 경로·본문을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  buildItems,
  canSend,
  firstId,
  formatListTime,
  formatTime,
  groupByDay,
  isNoGroup,
  lastId,
  mergeMessages,
  nextPollDelay,
  previewText,
  roomErrorMessage,
  shouldShowName,
  shouldShowTime,
  trimDraft,
} from "../src/features/family-chat/chatUtils.js";

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
const at = (y, mo, d, h, mi) => new Date(y, mo - 1, d, h, mi).toISOString();
const msg = (id, user_id, text = "hi", created_at = at(2026, 10, 23, 15, 20)) => ({ id, user_id, user_name: user_id, text, created_at });

test("mergeMessages: id 로 중복 제거하고 오름차순", () => {
  const merged = mergeMessages([msg(3, "a"), msg(1, "a")], [msg(2, "b"), msg(3, "a")]);
  assert.deepEqual(merged.map((m) => m.id), [1, 2, 3]);
});

test("mergeMessages: 임시 메시지는 맨 뒤, 서버 메시지가 오면 같은 글의 전송 중 임시 메시지는 사라진다", () => {
  const temp = { id: "tmp-1", clientId: "tmp-1", user_id: "me", text: "안녕", created_at: at(2026, 10, 23, 15, 21), status: "sending" };
  const failed = { ...temp, id: "tmp-2", clientId: "tmp-2", text: "실패글", status: "failed" };
  let list = mergeMessages([msg(1, "a")], [temp, failed]);
  assert.deepEqual(list.map((m) => m.id), [1, "tmp-1", "tmp-2"]);
  list = mergeMessages(list, [msg(2, "me", "안녕")]); // 폴링이 먼저 가져온 경우
  assert.deepEqual(list.map((m) => m.id), [1, 2, "tmp-2"]);
  list = mergeMessages(list, [msg(2, "me", "안녕")]); // 같은 id 는 중복되지 않는다
  assert.equal(list.length, 3);
  // 실패한 임시 메시지는 같은 글이 와도 남는다(사용자가 직접 정리)
  const same = mergeMessages([failed], [msg(5, "me", "실패글")]);
  assert.equal(same.length, 2);
});

test("lastId·firstId: 임시 메시지는 제외", () => {
  const temp = { id: "tmp-1", clientId: "tmp-1", status: "sending", user_id: "me", text: "x", created_at: at(2026, 10, 23, 1, 0) };
  assert.equal(lastId([msg(4, "a"), msg(9, "a"), temp]), 9);
  assert.equal(firstId([msg(4, "a"), msg(9, "a"), temp]), 4);
  assert.equal(lastId([]), 0);
  assert.equal(firstId([temp]), 0);
});

test("formatTime·formatListTime", () => {
  assert.equal(formatTime(at(2026, 10, 23, 15, 20)), "오후 3:20");
  assert.equal(formatTime(at(2026, 10, 23, 0, 5)), "오전 12:05");
  assert.equal(formatTime(at(2026, 10, 23, 12, 0)), "오후 12:00");
  const now = new Date(2026, 9, 23, 18, 0);
  assert.equal(formatListTime(at(2026, 10, 23, 9, 3), now), "오전 9:03");
  assert.equal(formatListTime(at(2026, 10, 22, 9, 3), now), "10월 22일");
  assert.equal(formatTime("엉터리"), "");
});

test("groupByDay·buildItems: 날짜별로 묶고 구분선과 이름 표시를 만든다", () => {
  const list = [
    msg(1, "a", "x", at(2026, 10, 22, 23, 50)),
    msg(2, "a", "y", at(2026, 10, 23, 8, 0)),
    msg(3, "a", "z", at(2026, 10, 23, 8, 1)),
    msg(4, "b", "w", at(2026, 10, 23, 8, 2)),
  ];
  const groups = groupByDay(list);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].label, "2026년 10월 22일 목요일");
  assert.equal(groups[1].messages.length, 3);
  const items = buildItems(list);
  assert.deepEqual(items.map((i) => i.type), ["day", "message", "day", "message", "message", "message"]);
  assert.deepEqual(items.filter((i) => i.type === "message").map((i) => i.showName), [true, true, false, true]); // 날짜가 바뀌면 이름을 다시 보여 준다
});

test("shouldShowName: 연속된 같은 사람이면 생략", () => {
  assert.equal(shouldShowName(undefined, msg(1, "a")), true);
  assert.equal(shouldShowName(msg(1, "a"), msg(2, "a")), false);
  assert.equal(shouldShowName(msg(1, "a"), msg(2, "b")), true);
});

test("trimDraft·canSend: 공백만이면 불가, 2000자 초과 불가", () => {
  assert.equal(trimDraft("  안녕 \n"), "안녕");
  assert.equal(canSend("   \n "), false);
  assert.equal(canSend(""), false);
  assert.equal(canSend(null), false);
  assert.equal(canSend("가".repeat(2000)), true);
  assert.equal(canSend("가".repeat(2001)), false);
});

test("previewText: 내 글은 '나: ', 줄바꿈은 공백으로, 없으면 안내", () => {
  assert.equal(previewText(null), "아직 대화가 없어요");
  assert.equal(previewText(msg(1, "me", "첫 줄\n둘째 줄"), "me"), "나: 첫 줄 둘째 줄");
  assert.equal(previewText(msg(1, "dad", "밥 먹자"), "me"), "밥 먹자");
});

test("nextPollDelay: 정상 3초, 실패마다 두 배, 최대 30초", () => {
  assert.equal(nextPollDelay(0), 3000);
  assert.equal(nextPollDelay(1), 6000);
  assert.equal(nextPollDelay(2), 12000);
  assert.equal(nextPollDelay(3), 24000);
  assert.equal(nextPollDelay(4), 30000);
  assert.equal(nextPollDelay(50), 30000);
});

test("오류 문구: 문구에 대화 내용 없음", () => {
  assert.match(roomErrorMessage({ code: "network_error" }), /연결/);
  assert.match(roomErrorMessage(new Error("boom")), /다시 시도/);
  assert.equal(isNoGroup({ status: 404 }), true);
  assert.equal(isNoGroup({ status: 500 }), false);
});

test("메시지 API: 경로·쿼리·본문, 대화 글자는 쿼리에 없고 Bearer 만", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({ path: u.pathname, search: u.search, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} });
    return json(200, []);
  };
  const client = await import("../src/shared/api/client.js");
  const api = await import("../src/features/family-chat/api.js");
  client.setSession({ accessToken: "access-1", refreshToken: "refresh-1" });
  await api.listMessages({ latest: true, limit: 50 });
  await api.listMessages({ beforeId: 12, limit: 50 });
  await api.listMessages({ afterId: 30 });
  await api.sendMessage("저녁 뭐 먹을까?");
  await api.getRoomInfo();
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.path}${c.search}`),
    [
      "GET /family-chat/messages?latest=true&limit=50",
      "GET /family-chat/messages?before_id=12&limit=50",
      "GET /family-chat/messages?after_id=30&limit=100",
      "POST /family-chat/messages",
      "GET /family-group/groups/me",
      "GET /family-group/groups/me/nicknames", // 내가 붙인 별명을 구성원 이름에 입히려고 함께 부른다
    ],
  );
  assert.deepEqual(calls[3].body, { text: "저녁 뭐 먹을까?" });
  assert.ok(calls.every((c) => !c.search.includes("%EC") && !c.search.includes("text=")));
  assert.equal(calls[0].headers.Authorization, "Bearer access-1");
  assert.equal(calls[0].headers["X-Gyeot-Token"], undefined);
  client.clearSession();
});

test("shouldShowTime: 같은 사람이 같은 분에 이어 보내면 마지막에만", () => {
  const m = (id, u, h, mi) => msg(id, u, "x", at(2026, 10, 23, h, mi));
  assert.equal(shouldShowTime(m(1, "a", 8, 0), undefined), true);
  assert.equal(shouldShowTime(m(1, "a", 8, 0), m(2, "a", 8, 0)), false);
  assert.equal(shouldShowTime(m(1, "a", 8, 0), m(2, "a", 8, 1)), true);
  assert.equal(shouldShowTime(m(1, "a", 8, 0), m(2, "b", 8, 0)), true);
  assert.equal(shouldShowTime(m(1, "a", 8, 0), { ...m(2, "a", 8, 0), status: "sending" }), true); // 전송 중·실패 메시지는 묶음을 끊는다
  assert.equal(shouldShowTime(m(1, "a", 8, 0), { ...m(2, "a", 8, 0), status: "failed" }), true);
  const items = buildItems([m(1, "a", 8, 0), m(2, "a", 8, 0), m(3, "a", 8, 5)]);
  assert.deepEqual(items.filter((i) => i.type === "message").map((i) => i.showTime), [false, true, true]);
});
