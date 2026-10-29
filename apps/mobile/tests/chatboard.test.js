// 게시판 목록 화면(지난 공지 포함)의 순수 함수·API 경로·서랍 행을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  ALREADY_GONE_NOTICE,
  BOARD_FILTERS,
  BOARD_PREVIEW_MAX,
  DELETED_NOTICE,
  boardA11y,
  boardAuthor,
  boardDeleteOutcome,
  boardEmptyText,
  boardErrorMessage,
  boardMeta,
  boardPreview,
  boardReducer,
  canLoadMoreBoard,
  canOpenOriginal,
  filterBoard,
  initialBoardState,
  mergeBoard,
  normalizeBoardItem,
  originalRoute,
} from "../src/features/family-chat/boardUtils.js";
import { buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";

process.env.TZ = "Asia/Seoul";
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
const post = (id, at, extra = {}) => ({
  id,
  message_id: 10,
  text: `공지 ${id}`,
  user_id: "mom",
  user_name: "엄마",
  message_created_at: "2026-10-24T01:00:00Z",
  posted_by: "dad",
  posted_by_name: "아빠",
  posted_at: at,
  is_current: false,
  message_deleted: false,
  ...extra,
});

test("normalizeBoardItem: 없는 값은 안전한 기본값, 숫자·불리언 변환", () => {
  const n = normalizeBoardItem({ id: "p1", message_id: "7", text: null, is_current: 1 });
  assert.equal(n.id, "p1");
  assert.equal(n.message_id, 7);
  assert.equal(n.text, "");
  assert.equal(n.is_current, true);
  assert.equal(n.message_deleted, false);
  assert.equal(normalizeBoardItem(null).id, "");
});

test("mergeBoard: 같은 id 는 새 값으로 바꾸고 올린 시각 최신순, 같은 시각은 id 큰 순", () => {
  const a = normalizeBoardItem(post("a", "2026-10-24T01:00:00Z"));
  const b = normalizeBoardItem(post("b", "2026-10-24T02:00:00Z"));
  const merged = mergeBoard([a], [post("b", "2026-10-24T02:00:00Z"), post("a", "2026-10-24T03:00:00Z", { text: "갱신" })]);
  assert.deepEqual(merged.map((i) => i.id), ["a", "b"]); // a 가 다시 올라와 최신
  assert.equal(merged[0].text, "갱신");
  const same = mergeBoard([], [post("a", "2026-10-24T01:00:00Z"), post("c", "2026-10-24T01:00:00Z")]);
  assert.deepEqual(same.map((i) => i.id), ["c", "a"]);
  assert.deepEqual(mergeBoard(undefined, undefined), []);
  assert.equal(b.id, "b");
});

test("filterBoard: 현재 공지 칩은 지금 올라 있는 것만", () => {
  const items = [normalizeBoardItem(post("a", "2026-10-24T01:00:00Z", { is_current: true })), normalizeBoardItem(post("b", "2026-10-24T00:00:00Z"))];
  assert.deepEqual(filterBoard(items, "current").map((i) => i.id), ["a"]);
  assert.equal(filterBoard(items, "all").length, 2);
  assert.deepEqual(BOARD_FILTERS.map((f) => f.key), ["all", "current"]);
  assert.deepEqual(filterBoard(undefined, "all"), []);
  assert.match(boardEmptyText("current"), /올라 있는 공지가 없어요/);
  assert.match(boardEmptyText("all"), /아직 게시판에 올린 공지가 없어요/);
});

test("boardPreview: 줄바꿈은 공백으로, 길면 말줄임표", () => {
  assert.equal(boardPreview({ text: "첫째 줄\n\n둘째   줄" }), "첫째 줄 둘째 줄");
  const long = boardPreview({ text: "가".repeat(BOARD_PREVIEW_MAX + 30) });
  assert.equal(long, `${"가".repeat(BOARD_PREVIEW_MAX)}…`);
  assert.equal(boardPreview({ text: "가".repeat(BOARD_PREVIEW_MAX) }), "가".repeat(BOARD_PREVIEW_MAX));
  assert.equal(boardPreview(null), "");
});

test("boardMeta·boardAuthor: 올린 사람(별명 우선)과 시각, 쓴 사람은 올린 사람과 다를 때만", () => {
  const item = post("a", "2026-10-24T06:20:00Z"); // 한국 시간 오후 3:20
  assert.equal(boardMeta(item), "아빠 올림 · 10월 24일 오후 3:20");
  assert.equal(boardMeta(item, (id) => (id === "dad" ? "우리 아빠" : undefined)), "우리 아빠 올림 · 10월 24일 오후 3:20");
  assert.equal(boardMeta({ posted_by_name: "", posted_at: "이상한값" }), "가족 올림");
  assert.equal(boardAuthor(item), "엄마 님이 쓴 글");
  assert.equal(boardAuthor(item, (id) => (id === "mom" ? "우리 엄마" : undefined)), "우리 엄마 님이 쓴 글");
  assert.equal(boardAuthor({ ...item, user_id: "dad" }), null);
  assert.equal(boardAuthor({ ...item, user_id: "" }), null);
});

test("boardA11y: 현재/지난 공지, 원본 삭제 안내", () => {
  const label = boardA11y(post("a", "2026-10-24T06:20:00Z", { is_current: true }));
  assert.match(label, /^현재 공지, 공지 a\./);
  assert.match(label, /누르면 전체 내용을 봐요$/);
  assert.match(boardA11y(post("a", "2026-10-24T06:20:00Z", { message_deleted: true })), /^지난 공지,.*원본 메시지는 삭제됐어요/);
});

test("오류 문구: 상태별", () => {
  assert.equal(boardErrorMessage({ status: 404 }), "채팅방을 찾을 수 없어요");
  assert.equal(boardErrorMessage({ status: 429 }), "잠시 후 다시 시도해 주세요");
  assert.equal(boardErrorMessage({ status: 0 }), "서버에 연결하지 못했어요");
  assert.equal(boardErrorMessage(null), "게시판을 불러오지 못했어요");
});

test("boardDeleteOutcome: 성공·404 는 목록에서 빼고, 그 밖의 실패는 그대로 둔다", () => {
  assert.deepEqual(boardDeleteOutcome(null), { effect: "remove", notice: DELETED_NOTICE });
  assert.deepEqual(boardDeleteOutcome({ status: 404 }), { effect: "remove", notice: ALREADY_GONE_NOTICE });
  assert.deepEqual(boardDeleteOutcome({ status: 429 }), { effect: "keep", notice: "잠시 후 다시 시도해 주세요" });
  assert.deepEqual(boardDeleteOutcome({ status: 0 }), { effect: "keep", notice: "서버에 연결하지 못했어요" });
  assert.deepEqual(boardDeleteOutcome({ status: 500 }), { effect: "keep", notice: "삭제하지 못했어요" });
});

test("canOpenOriginal·originalRoute: 원본이 남아 있을 때만, 검색 결과와 같은 경로 형식", () => {
  assert.equal(canOpenOriginal({ message_deleted: false }), true);
  assert.equal(canOpenOriginal({ message_deleted: true }), false);
  assert.equal(canOpenOriginal(null), false);
  assert.deepEqual(originalRoute({ messageId: 42 }), { pathname: "/chat-room", params: { focus: "42" } });
  assert.deepEqual(originalRoute({ roomId: "r1", peerId: "u2", messageId: 42 }), { pathname: "/chat-room", params: { focus: "42", roomId: "r1", peer: "u2" } });
});

test("boardReducer: 첫 쪽·다음 쪽·옛 응답 무시·삭제", () => {
  let st = boardReducer(initialBoardState(), { type: "start", seq: 1 });
  assert.equal(st.status, "loading");
  st = boardReducer(st, { type: "firstOk", seq: 1, page: { items: [post("a", "2026-10-24T03:00:00Z"), post("b", "2026-10-24T02:00:00Z")], next_before: "CUR" } });
  assert.equal(st.status, "ready");
  assert.deepEqual(st.items.map((i) => i.id), ["a", "b"]);
  assert.equal(canLoadMoreBoard(st), true);

  st = boardReducer(st, { type: "moreStart", seq: 1 });
  assert.equal(canLoadMoreBoard(st), false); // 받는 중
  const failed = boardReducer(st, { type: "moreFail", seq: 1, error: { status: 0 } });
  assert.equal(failed.error, "서버에 연결하지 못했어요");
  assert.equal(failed.items.length, 2); // 이미 받은 목록은 그대로
  assert.equal(canLoadMoreBoard(failed), true); // 다시 시도 가능
  st = boardReducer(st, { type: "moreOk", seq: 1, page: { items: [post("c", "2026-10-24T01:00:00Z")], next_before: null } });
  assert.deepEqual(st.items.map((i) => i.id), ["a", "b", "c"]);
  assert.equal(canLoadMoreBoard(st), false); // 더 없음

  assert.equal(boardReducer(st, { type: "firstOk", seq: 9, page: { items: [] } }), st); // 옛 요청의 응답
  st = boardReducer(st, { type: "removed", id: "b" });
  assert.deepEqual(st.items.map((i) => i.id), ["a", "c"]);
  st = boardReducer(st, { type: "start", seq: 2 });
  assert.deepEqual(st.items, []); // 방이 바뀌면 비운다

  const failedFirst = boardReducer(boardReducer(initialBoardState(), { type: "start", seq: 3 }), { type: "firstFail", seq: 3, error: { status: 404 } });
  assert.equal(failedFirst.status, "error");
  assert.equal(failedFirst.error, "채팅방을 찾을 수 없어요");
});

test("API listBoard·deleteBoardPost: 경로·메서드·커서 인코딩", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET" });
    if (init.method === "DELETE") return new Response(null, { status: 204 });
    return json(200, { items: [], next_before: null });
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.listBoard();
  await api.listBoard({ roomId: "r 1", limit: 5, before: "a+b/c=" });
  const removed = await api.deleteBoardPost({ postId: "p1" });
  await api.deleteBoardPost({ roomId: "r1", postId: "p 2" });
  assert.match(calls[0].url, /\/family-chat\/board\?limit=20$/);
  assert.match(calls[1].url, /\/family-chat\/board\?room_id=r%201&limit=5&before=a%2Bb%2Fc%3D$/);
  assert.equal(calls[2].method, "DELETE");
  assert.match(calls[2].url, /\/family-chat\/board\/p1$/);
  assert.match(calls[3].url, /\/family-chat\/board\/p%202\?room_id=r1$/);
  assert.equal(removed, null);
});

test("서랍: 게시판 행은 가족방·1:1 모두 동작 행이다", () => {
  const find = (sections, key) => sections.flatMap((s) => s.rows).find((r) => r.key === key);
  for (const direct of [false, true]) {
    const row = find(buildDrawerSections({ direct, pinsReady: true }), "pins");
    assert.equal(row.state, "open");
    assert.deepEqual(resolveRowAction(row), { type: "pins" });
  }
});
