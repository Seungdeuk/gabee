// 대화 검색(돋보기) 순수 함수와 API 경로·쿼리·커서·오류 문구를 가짜 서버로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { focusErrorMessage, lastId, searchErrorMessage } from "../src/features/family-chat/chatUtils.js";
import {
  applySaved,
  applySavedNow,
  beginTransition,
  canReuseLiveRun,
  canLoadNewer,
  canLoadOlder,
  canPoll,
  enterLiveEnd,
  finishTransition,
  initialModeState,
  needsLiveBeforeSend,
  retryTarget,
  tokenValid,
  windowToken,
} from "../src/features/family-chat/focusMode.js";
import {
  familyRoomId,
  searchScopeRoomId,
  roomSearchOptions,
  focusRoute,
  formatSearchTime,
  highlightRanges,
  isLatestRequest,
  keepTemps,
  mergeSearchResults,
  normalizeQuery,
  parseFocusParam,
  previewSnippet,
  reachedLiveEnd,
  replaceWindow,
  resultCountLabel,
  searchRoomLabel,
  searchTerms,
  shouldLoadNewer,
  shouldRunSearch,
  splitHighlight,
} from "../src/features/family-chat/searchUtils.js";

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
const m = (id, extra = {}) => ({ id, user_id: "u", user_name: "x", text: `t${id}`, created_at: "2026-10-23T06:00:00Z", ...extra });

test("searchTerms/normalizeQuery: 공백으로 나누고 빈 낱말·대소문자 중복을 없애며 100자로 자른다", () => {
  assert.deepEqual(searchTerms("  저녁   Pizza  pizza "), ["저녁", "Pizza"]);
  assert.deepEqual(searchTerms("   "), []);
  assert.deepEqual(searchTerms(null), []);
  assert.equal(normalizeQuery("  저녁   약속 "), "저녁 약속");
  assert.equal(normalizeQuery("   "), "");
  assert.equal(normalizeQuery("가".repeat(150)).length, 100);
});

test("shouldRunSearch/isLatestRequest: 공백만이면 부르지 않고, 같은 검색어는 다시 부르지 않으며, 오래된 응답은 버린다", () => {
  assert.equal(shouldRunSearch("", ""), false);
  assert.equal(shouldRunSearch("저녁", ""), true);
  assert.equal(shouldRunSearch("저녁", "저녁"), false);
  assert.equal(shouldRunSearch("저녁 약속", "저녁"), true);
  assert.equal(isLatestRequest(3, 3), true);
  assert.equal(isLatestRequest(2, 3), false);
});

test("highlightRanges: 여러 낱말·대소문자 무시·겹침 병합·맞닿음 병합", () => {
  assert.deepEqual(highlightRanges("Hello hello", ["hello"]), [
    { start: 0, end: 5 },
    { start: 6, end: 11 },
  ]);
  assert.deepEqual(highlightRanges("저녁 약속 있어요", ["약속", "저녁"]), [
    { start: 0, end: 2 },
    { start: 3, end: 5 },
  ]);
  assert.deepEqual(highlightRanges("abcdef", ["abc", "cde"]), [{ start: 0, end: 5 }]); // 겹침
  assert.deepEqual(highlightRanges("abcdef", ["abc", "def"]), [{ start: 0, end: 6 }]); // 맞닿음
  assert.deepEqual(highlightRanges("aaaa", ["aa"]), [{ start: 0, end: 4 }]);
  assert.deepEqual(highlightRanges("", ["a"]), []);
  assert.deepEqual(highlightRanges("abc", []), []);
  assert.deepEqual(highlightRanges("abc", [""]), []);
});

test("highlightRanges: 특수문자는 글자 그대로 찾고(정규식 아님), 한글은 조합된 글자 그대로 비교한다", () => {
  assert.deepEqual(highlightRanges("가격은 (1+1) 이에요? .*", ["(1+1)", ".*", "?"]), [
    { start: 4, end: 9 },
    { start: 13, end: 14 },
    { start: 15, end: 17 },
  ]);
  assert.deepEqual(highlightRanges("한글 한국", ["한"]), [
    { start: 0, end: 1 },
    { start: 3, end: 4 },
  ]);
  assert.deepEqual(highlightRanges("한글", ["ㅎ"]), []); // 자모만으로는 찾지 않는다
  assert.deepEqual(highlightRanges("😀 hi 😀", ["😀"]), [
    { start: 0, end: 2 },
    { start: 6, end: 8 },
  ]);
});

test("highlightRanges: 소문자로 바꾸면 길이가 달라지는 글자가 섞여도 위치가 어긋나지 않는다", () => {
  const text = "İstanbul istanbul";
  const ranges = highlightRanges(text, ["istanbul"]);
  for (const r of ranges) assert.equal(text.slice(r.start, r.end), "istanbul"); // 원문 그대로 비교로 물러난다
});

test("splitHighlight: 강조·일반 조각으로 나누고 이어 붙이면 원문과 같다", () => {
  const parts = splitHighlight("오늘 저녁 뭐 먹지 저녁", ["저녁"]);
  assert.deepEqual(parts, [
    { text: "오늘 ", hit: false },
    { text: "저녁", hit: true },
    { text: " 뭐 먹지 ", hit: false },
    { text: "저녁", hit: true },
  ]);
  assert.equal(parts.map((p) => p.text).join(""), "오늘 저녁 뭐 먹지 저녁");
  assert.deepEqual(splitHighlight("그냥 글", ["없음"]), [{ text: "그냥 글", hit: false }]);
  assert.deepEqual(splitHighlight("", ["a"]), []);
});

test("previewSnippet: 줄바꿈을 줄이고, 일치가 멀리 있으면 앞을 잘라 일치가 보이게 한다", () => {
  assert.equal(previewSnippet("안녕\n\n  하세요", ["안녕"]), "안녕 하세요");
  const long = `${"가".repeat(80)}목표${"나".repeat(10)}`;
  const snippet = previewSnippet(long, ["목표"]);
  assert.ok(snippet.startsWith("…"));
  assert.ok(snippet.includes("목표"));
  assert.ok(snippet.length < long.length);
  assert.equal(previewSnippet("짧은 글 목표", ["목표"]), "짧은 글 목표");
});

test("formatSearchTime: 오늘은 시각, 올해는 월일, 다른 해는 연월일", () => {
  const now = new Date(2026, 9, 26, 12, 0);
  assert.equal(formatSearchTime(new Date(2026, 9, 26, 15, 20).toISOString(), now), "오후 3:20");
  assert.equal(formatSearchTime(new Date(2026, 8, 3, 9, 0).toISOString(), now), "9월 3일");
  assert.equal(formatSearchTime(new Date(2025, 11, 31, 9, 0).toISOString(), now), "2025년 12월 31일");
  assert.equal(formatSearchTime("엉터리", now), "");
});

test("mergeSearchResults: id 중복 제거 후 최신(큰 id)이 먼저, resultCountLabel 은 더 있으면 '이상'", () => {
  const merged = mergeSearchResults([m(9), m(7)], [m(7, { text: "새" }), m(5), m(8)]);
  assert.deepEqual(merged.map((x) => x.id), [9, 8, 7, 5]);
  assert.equal(merged.find((x) => x.id === 7).text, "새");
  assert.deepEqual(mergeSearchResults(undefined, undefined), []);
  assert.equal(resultCountLabel(20, true), "20개 이상");
  assert.equal(resultCountLabel(3, false), "3개");
});

test("searchRoomLabel: 목록의 방 이름 우선, 없으면 종류·구성원으로, 모르면 '대화'", () => {
  const rooms = [
    { id: "rf", name: "우리 가족" },
    { id: "rm", name: "우리 엄마" },
  ];
  const members = [{ id: "dad", name: "아빠" }];
  assert.equal(searchRoomLabel({ room_id: "rf", room_kind: "family" }, rooms, members), "우리 가족");
  assert.equal(searchRoomLabel({ room_id: "rm", room_kind: "direct", peer_user_id: "mom" }, rooms, members), "우리 엄마");
  assert.equal(searchRoomLabel({ room_id: "new", room_kind: "direct", peer_user_id: "dad" }, rooms, members), "아빠");
  assert.equal(searchRoomLabel({ room_id: "new", room_kind: "direct", peer_user_id: "gone" }, rooms, members), "대화");
  assert.equal(searchRoomLabel({ room_id: "new", room_kind: "family" }, [], []), "가족 채팅");
  assert.equal(searchRoomLabel({ room_id: "x" }, undefined, undefined), "대화");
});

test("focusRoute/parseFocusParam: 가족 전체방은 focus 만, 1:1 은 roomId·peer 와 focus 를 넘기고 focus 는 양의 정수만 받는다", () => {
  assert.deepEqual(focusRoute({ id: 42, room_id: "rf", room_kind: "family", peer_user_id: null }), { pathname: "/chat-room", params: { focus: "42" } });
  assert.deepEqual(focusRoute({ id: 7, room_id: "rm", room_kind: "direct", peer_user_id: "mom" }), { pathname: "/chat-room", params: { focus: "7", roomId: "rm", peer: "mom" } });
  assert.equal(parseFocusParam("42"), 42);
  assert.equal(parseFocusParam(["9"]), 9);
  for (const bad of ["0", "-3", "1.5", "abc", "", undefined, null, 12, "9".repeat(20)]) assert.equal(parseFocusParam(bad), null, String(bad));
});

test("replaceWindow: 서버 메시지는 창으로 통째로 바꾸고(중복 제거·오름차순) 임시 메시지는 유지한다", () => {
  const existing = [m(100), m(101), m(102), { ...m("tmp-1"), clientId: "tmp-1", status: "sending" }, { ...m("tmp-2"), clientId: "tmp-2", status: "failed" }];
  const next = replaceWindow(existing, [m(12), m(10), m(11), m(11), m(13)]);
  assert.deepEqual(next.slice(0, 4).map((x) => x.id), [10, 11, 12, 13]);
  assert.deepEqual(next.slice(4).map((x) => x.clientId), ["tmp-1", "tmp-2"]);
  assert.equal(next.length, 6);
  assert.deepEqual(keepTemps(existing).map((x) => x.clientId), ["tmp-1", "tmp-2"]);
  assert.deepEqual(replaceWindow(undefined, undefined), []);
});

test("reachedLiveEnd/shouldLoadNewer: 요청한 개수보다 적게 오면 라이브 끝, 과거 창에서 아래 끝 근처일 때만 이후 대화를 받는다", () => {
  assert.equal(reachedLiveEnd(49, 50), true);
  assert.equal(reachedLiveEnd(0, 50), true);
  assert.equal(reachedLiveEnd(50, 50), false);
  assert.equal(shouldLoadNewer({ focusing: true, fromBottom: 50, near: 120, busy: false }), true);
  assert.equal(shouldLoadNewer({ focusing: true, fromBottom: 500, near: 120, busy: false }), false);
  assert.equal(shouldLoadNewer({ focusing: false, fromBottom: 0, near: 120, busy: false }), false); // 라이브에서는 불필요
  assert.equal(shouldLoadNewer({ focusing: true, fromBottom: 0, near: 120, busy: true }), false);
});

test("오류 문구: 429·422 는 상태로 알아보고 검색어·결과 글자는 넣지 않는다", () => {
  assert.match(searchErrorMessage({ status: 429, code: "too_many_searches" }), /너무 자주/);
  assert.match(searchErrorMessage({ status: 429 }), /너무 자주/);
  assert.match(searchErrorMessage({ status: 422, code: "validation_error" }), /1자에서 100자/);
  assert.match(searchErrorMessage({ status: 0, code: "network_error" }), /연결하지 못했어요/);
  assert.match(searchErrorMessage({ status: 404, code: "not_found" }), /대화방을 찾을 수 없어요/);
  assert.match(searchErrorMessage(undefined), /잠시 문제가 생겼어요/);
  assert.match(focusErrorMessage({ status: 400, code: "invalid_message" }), /최근 대화/);
  assert.match(focusErrorMessage({ status: 404 }), /최근 대화/);
  assert.match(focusErrorMessage({ status: 0, code: "network_error" }), /연결하지 못했어요/);
});

test("API searchMessages: 경로·인코딩·room_id·limit·커서, GET 이고 본문 없음", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    return json(200, { items: [{ id: 5, room_id: "r1", room_kind: "family", peer_user_id: null, user_id: "u", user_name: "x", text: "저녁", created_at: "2026-10-23T06:00:00Z" }], next_before_id: 5 });
  };
  const api = await import("../src/features/family-chat/api.js");

  const page = await api.searchMessages({ q: "저녁 약속&a=b#c", roomId: "r 1", limit: 20, beforeId: 30 });
  await api.searchMessages({ q: "a" });
  assert.equal(page.next_before_id, 5);
  assert.equal(calls[0].method, "GET");
  assert.equal(calls[0].body, undefined);
  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/family-chat/search");
  assert.equal(url.searchParams.get("q"), "저녁 약속&a=b#c"); // 인코딩되어 쿼리 하나로 들어간다
  assert.equal(url.searchParams.get("room_id"), "r 1");
  assert.equal(url.searchParams.get("limit"), "20");
  assert.equal(url.searchParams.get("before_id"), "30");
  assert.equal(url.searchParams.size, 4);
  assert.equal(calls[1].url, "http://api.test/family-chat/search?q=a&limit=20"); // room_id·커서 없으면 붙지 않는다
});

test("API searchMessages: 429·422 는 상태가 담긴 오류로 던진다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  globalThis.fetch = async () => json(429, { code: "too_many_searches", message: "x" });
  await assert.rejects(() => api.searchMessages({ q: "a" }), (e) => e.status === 429 && searchErrorMessage(e).includes("너무 자주"));
  globalThis.fetch = async () => json(422, { code: "validation_error", message: "x" });
  await assert.rejects(() => api.searchMessages({ q: "a" }), (e) => e.status === 422 && searchErrorMessage(e).includes("100자"));
});

test("API listMessages: aroundId 는 around_id 만(다른 범위와 함께 보내지 않음), 기존 호출은 그대로", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    return json(200, []);
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.listMessages({ aroundId: 42, limit: 50, roomId: "r1" });
  await api.listMessages({ aroundId: 42, latest: true, beforeId: 1, afterId: 2, limit: 50 });
  await api.listMessages({ latest: true, limit: 50 });
  await api.listMessages({ afterId: 7, limit: 100, roomId: "r 1" });
  assert.deepEqual(urls, [
    "http://api.test/family-chat/messages?around_id=42&limit=50&room_id=r1",
    "http://api.test/family-chat/messages?around_id=42&limit=50",
    "http://api.test/family-chat/messages?latest=true&limit=50",
    "http://api.test/family-chat/messages?after_id=7&limit=100&room_id=r%201",
  ]);
});

test("focusMode: focusOn 성공 -> 과거 모드, 폴링 멈춤, 위/아래 불러오기는 전환이 끝난 뒤에만", () => {
  let s = initialModeState(null);
  assert.deepEqual(s, { mode: "live", gen: 0, busy: null });
  assert.equal(canPoll(s), true);
  assert.equal(canLoadNewer(s), false); // 라이브에서는 아래로 불러오지 않는다
  s = beginTransition(s, "focus");
  assert.deepEqual(s, { mode: "past", gen: 1, busy: "focus" });
  assert.equal(canPoll(s), false);
  assert.equal(canLoadOlder(s), false); // 창을 바꾸는 중에는 막는다
  assert.equal(canLoadNewer(s), false);
  const fin = finishTransition(s, 1, "focus", true);
  assert.equal(fin.applied, true);
  assert.deepEqual(fin.state, { mode: "past", gen: 1, busy: null });
  assert.equal(canLoadNewer(fin.state), true);
  assert.equal(canPoll(fin.state), false);
  assert.deepEqual(initialModeState(42), { mode: "past", gen: 0, busy: null }); // focus 인자로 열면 처음부터 과거
});

test("focusMode: focusOn 실패 후 라이브 복귀도 실패하면 과거 모드에 머물고 busy 는 풀려 다시 시도할 수 있다", () => {
  let s = beginTransition(initialModeState(7), "focus");
  s = finishTransition(s, s.gen, "focus", false).state;
  assert.deepEqual(s, { mode: "past", gen: 1, busy: null });
  s = beginTransition(s, "live");
  assert.equal(s.mode, "past"); // 복귀 중에도 아직 과거
  const failed = finishTransition(s, s.gen, "live", false);
  assert.equal(failed.applied, true);
  assert.deepEqual(failed.state, { mode: "past", gen: 2, busy: null });
  assert.equal(retryTarget("live", failed.state), "live");
  assert.equal(retryTarget("focus", failed.state), "live");
  const ok = finishTransition(beginTransition(failed.state, "live"), 3, "live", true);
  assert.equal(ok.state.mode, "live");
  assert.equal(canPoll(ok.state), true);
});

test("focusMode: 세대 번호가 어긋난 응답은 버린다(전환이 겹칠 때, 위/아래 불러오기 중 전환)", () => {
  let s = beginTransition(initialModeState(null), "focus"); // gen 1
  const stale = beginTransition(s, "live"); // gen 2 가 먼저 시작됨
  assert.equal(finishTransition(stale, 1, "focus", true).applied, false);
  assert.deepEqual(finishTransition(stale, 1, "focus", true).state, stale);
  // 불러오기 요청이 들고 있던 표는 전환 뒤에 무효
  s = finishTransition(s, 1, "focus", true).state;
  const token = windowToken(s);
  assert.equal(tokenValid(s, token), true);
  assert.equal(tokenValid(beginTransition(s, "focus"), token), false);
  assert.equal(tokenValid(enterLiveEnd(s), token), false); // 라이브로 바뀌면 과거 모드 요청의 응답은 버린다
});

test("focusMode: 전송 계열은 과거 모드(또는 전환 중)에서 라이브 복귀가 먼저 필요하다", () => {
  assert.equal(needsLiveBeforeSend(initialModeState(null)), false);
  assert.equal(needsLiveBeforeSend(initialModeState(3)), true);
  assert.equal(needsLiveBeforeSend(beginTransition(initialModeState(null), "focus")), true);
  assert.equal(needsLiveBeforeSend(enterLiveEnd(initialModeState(3))), false);
});

test("applySaved: 라이브에서는 서버 메시지를 병합, 과거 창에는 병합하지 않고 임시만 지운다(loadNewer 기준이 앞서가지 않게)", () => {
  const win = [m(10), m(11), m(12), { ...m("tmp-1"), clientId: "tmp-1", status: "sending" }];
  const saved = m(500);
  assert.deepEqual(applySaved(win, saved, "live", "tmp-1").map((x) => x.id), [10, 11, 12, 500]);
  const past = applySaved(win, saved, "past", "tmp-1");
  assert.deepEqual(past.map((x) => x.id), [10, 11, 12]);
  assert.equal(lastId(past), 12); // 이후 loadNewer 는 12 부터 받는다
  assert.equal(lastId(win), 12); // 임시 메시지는 기준에서 제외
  assert.deepEqual(applySaved([m(1)], m(2), "past", null).map((x) => x.id), [1]); // 사진: 임시 없음
});

test("retryTarget: 라이브는 새 메시지 확인, 과거는 마지막 실패한 위/아래 불러오기 또는 라이브 복귀", () => {
  const live = initialModeState(null);
  const past = initialModeState(5);
  assert.equal(retryTarget("older", live), "poll");
  assert.equal(retryTarget(null, live), "poll");
  assert.equal(retryTarget("older", past), "older");
  assert.equal(retryTarget("newer", past), "newer");
  assert.equal(retryTarget(null, past), "live");
});

test("가족방 검색 범위: 방 목록의 family 행 id 를 쓰고, 모르면 null(검색 비활성), 1:1 은 경로의 방 id", () => {
  const rooms = [{ id: "rm", kind: "direct" }, { id: "rf", kind: "family" }];
  assert.equal(familyRoomId(rooms), "rf");
  assert.equal(familyRoomId([{ id: "rm", kind: "direct" }]), null);
  assert.equal(familyRoomId(undefined), null);
  assert.equal(searchScopeRoomId(null, "rf"), "rf");
  assert.equal(searchScopeRoomId(null, null), null);
  assert.equal(searchScopeRoomId("rm", "rf"), "rm");
});

test("API searchMessages: 가족방 id 를 room_id 로 넘기면 쿼리에 들어간다(전체 방 검색과 구분)", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    return json(200, { items: [], next_before_id: null });
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.searchMessages({ q: "a", roomId: "rf" });
  await api.searchMessages({ q: "a", roomId: null });
  assert.equal(new URL(urls[0]).searchParams.get("room_id"), "rf");
  assert.equal(new URL(urls[1]).searchParams.has("room_id"), false);
});

test("canReuseLiveRun: 같은 세대의 복귀 전환 중일 때만 재사용, 세대가 올라갔거나 전환이 끝났으면 새로 시작", () => {
  let s = beginTransition(initialModeState(5), "live"); // gen 1
  const run = { gen: s.gen };
  assert.equal(canReuseLiveRun(run, s), true);
  assert.equal(canReuseLiveRun(null, s), false);
  const moved = beginTransition(s, "focus"); // 복귀 중 검색 결과 이동 -> gen 2
  assert.equal(canReuseLiveRun(run, moved), false); // 무효가 된 요청을 기다리지 않는다
  assert.equal(canReuseLiveRun(run, finishTransition(s, 1, "live", false).state), false); // 이미 끝남
  const again = beginTransition(moved, "live"); // 새로 시작
  assert.equal(canReuseLiveRun({ gen: again.gen }, again), true);
});

test("연결 헬퍼: 방 안 검색 옵션은 항상 scoped, 방 id 를 모르면 null; applySavedNow 는 저장 완료 시점의 모드를 따른다", () => {
  assert.deepEqual(roomSearchOptions(null, null), { roomId: null, scoped: true });
  assert.deepEqual(roomSearchOptions(null, "rf"), { roomId: "rf", scoped: true });
  assert.deepEqual(roomSearchOptions("rm", "rf"), { roomId: "rm", scoped: true });
  const win = [m(1), { ...m("t"), clientId: "t", status: "sending" }];
  assert.deepEqual(applySavedNow(win, m(9), { mode: "live" }, "t").map((x) => x.id), [1, 9]);
  assert.deepEqual(applySavedNow(win, m(9), { mode: "past" }, "t").map((x) => x.id), [1]);
});
