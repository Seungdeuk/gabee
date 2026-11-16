// 가족 타임라인(T05-d) 순수 함수·상태 전이·빼기 흐름·서랍 진입·API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";
import {
  EXCLUDED_NOTICE,
  SENT_DAY_NOTE,
  TIMELINE_ENTRY_KEY,
  TIMELINE_LOAD_FAILED,
  UNKNOWN_DAY,
  buildTimelineRows,
  canExclude,
  canLoadMoreTimeline,
  initialTimelineState,
  isGoneFromTimeline,
  kstParts,
  photoCaption,
  runExclude,
  timelineBodyKind,
  timelineErrorMessage,
  timelineReducer,
} from "../src/features/family-chat/timeline.js";

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
const photo = (id, display_at = "2026-11-16T03:00:00Z", extra = {}) => ({
  attachment_id: id,
  message_id: Number(String(id).replace(/\D/g, "")) || 1,
  thumb_url: `/family-chat/photos/${id}?size=thumb`,
  display_at,
  taken_at: display_at,
  created_at: display_at,
  batch_id: null,
  mine: false,
  ...extra,
});
const page = (items, next = null) => ({ items, next_before: next });
const rows = (sections) => sections.flatMap((s) => s.rows);

// ---- 한국 시간 날짜 --------------------------------------------------------------------------

test("kstParts: UTC 시각을 한국 시간 날짜로(자정 경계가 하루 앞서간다)", () => {
  assert.deepEqual(kstParts("2026-11-15T14:59:59Z"), { y: 2026, m: 11, d: 15 });
  assert.deepEqual(kstParts("2026-11-15T15:00:00Z"), { y: 2026, m: 11, d: 16 }); // 한국은 UTC+9
  assert.deepEqual(kstParts("2026-12-31T16:00:00+00:00"), { y: 2027, m: 1, d: 1 }); // 연말 경계
  assert.deepEqual(kstParts("2026-11-16T09:00:00+09:00"), { y: 2026, m: 11, d: 16 }); // 시간대 표기를 따른다
});

test("kstParts: 읽을 수 없는 값은 null", () => {
  for (const bad of [undefined, null, "", "어제", "2026-13-40", 12345, {}]) assert.equal(kstParts(bad), null, String(bad));
});

test("photoCaption: 촬영일이 없으면 '보낸 날 기준'을 붙이고, 있으면 날짜만(촬영일을 단정하지 않는다)", () => {
  assert.equal(photoCaption({ display_at: "2026-11-15T15:30:00Z", taken_at: "2026-11-15T15:30:00Z" }), "2026년 11월 16일");
  assert.equal(photoCaption({ display_at: "2026-11-15T15:30:00Z", taken_at: null }), `2026년 11월 16일 · ${SENT_DAY_NOTE}`);
  assert.equal(photoCaption({ display_at: "깨진 값", taken_at: null }), UNKNOWN_DAY);
  assert.equal(photoCaption(undefined), UNKNOWN_DAY);
});

// ---- 날짜 묶음 -------------------------------------------------------------------------------

test("buildTimelineRows: 월 머리글 → 날짜 → 사진 줄(한 줄 3장), 날짜가 바뀔 때만 머리글", () => {
  const items = [
    photo("a1", "2026-11-16T03:00:00Z"),
    photo("a2", "2026-11-16T02:00:00Z"),
    photo("a3", "2026-11-16T01:00:00Z"),
    photo("a4", "2026-11-16T00:30:00Z"),
    photo("b1", "2026-11-10T03:00:00Z"),
    photo("c1", "2026-10-30T03:00:00Z"),
  ];
  const out = buildTimelineRows(items);
  assert.deepEqual(
    out.map((r) => (r.type === "photos" ? r.items.map((i) => i.attachment_id).join(",") : `${r.type}:${r.title}`)),
    ["month:2026년 11월", "day:11월 16일", "a1,a2,a3", "a4", "day:11월 10일", "b1", "month:2026년 10월", "day:10월 30일", "c1"],
  );
  assert.equal(new Set(out.map((r) => r.key)).size, out.length); // 목록 key 가 겹치지 않는다
});

test("buildTimelineRows: 한국 시간 기준으로 같은 날이면 UTC 날짜가 달라도 한 날짜로 묶는다", () => {
  const out = buildTimelineRows([photo("x1", "2026-11-15T15:10:00Z"), photo("x2", "2026-11-15T20:00:00Z")]); // 둘 다 한국 11월 16일
  assert.equal(out.filter((r) => r.type === "day").length, 1);
  assert.equal(out.find((r) => r.type === "day").title, "11월 16일");
});

test("buildTimelineRows: 읽을 수 없는 날짜의 사진도 버리지 않고 한 칸에 모은다", () => {
  const out = buildTimelineRows([photo("a1", "2026-11-16T03:00:00Z"), photo("z1", "깨진 값"), { ...photo("z2"), display_at: undefined }]);
  const titles = out.filter((r) => r.type === "month").map((r) => r.title);
  assert.deepEqual(titles, ["2026년 11월", UNKNOWN_DAY]);
  assert.deepEqual(out.filter((r) => r.type === "photos").flatMap((r) => r.items.map((i) => i.attachment_id)), ["a1", "z1", "z2"]);
});

test("buildTimelineRows: 빈 목록·없는 값은 빈 배열, 열 수를 바꿀 수 있다", () => {
  assert.deepEqual(buildTimelineRows([]), []);
  assert.deepEqual(buildTimelineRows(undefined), []);
  const out = buildTimelineRows([photo("a1"), photo("a2"), photo("a3")], 2);
  assert.deepEqual(out.filter((r) => r.type === "photos").map((r) => r.items.length), [2, 1]);
});

// ---- 빼기 권한·오류 문구 ---------------------------------------------------------------------

test("canExclude: 서버가 mine 으로 표시한 내 사진만(문자열·undefined 는 아니다)", () => {
  assert.equal(canExclude({ mine: true }), true);
  for (const bad of [{ mine: false }, { mine: "true" }, { mine: 1 }, {}, null, undefined]) assert.equal(canExclude(bad), false, JSON.stringify(bad));
});

test("timelineErrorMessage: 오류별 사용자 문구, 서버 문구·내부 사정은 그대로 보이지 않는다", () => {
  assert.match(timelineErrorMessage({ status: 409, code: "not_in_timeline", message: "서버 문구" }), /이미 타임라인에 없어요/);
  assert.match(timelineErrorMessage({ status: 422, code: "invalid_cursor" }), /다시 불러/);
  assert.match(timelineErrorMessage({ status: 503, code: "photo_checks_unavailable" }), /불러오지 못/);
  assert.match(timelineErrorMessage({ status: 429, code: "too_many_checks", retryAfter: 30 }), /30초 뒤/);
  assert.match(timelineErrorMessage({ status: 404, code: "not_found" }), /확인할 수 없/);
  assert.match(timelineErrorMessage({ code: "network_error" }), /연결/);
  assert.doesNotMatch(timelineErrorMessage({ status: 500, code: "boom", message: "SQLSTATE secret" }), /SQLSTATE|secret/);
  assert.equal(timelineErrorMessage(null), "");
});

test("isGoneFromTimeline: 404·not_in_timeline 만 '이미 없음', 일시 오류는 남긴다", () => {
  assert.equal(isGoneFromTimeline({ status: 404 }), true);
  assert.equal(isGoneFromTimeline({ status: 409, code: "not_in_timeline" }), true);
  for (const e of [{ status: 503 }, { status: 429 }, { code: "network_error" }, { status: 409, code: "other" }, null, undefined]) assert.equal(isGoneFromTimeline(e), false, JSON.stringify(e));
});

// ---- 목록 상태 전이 --------------------------------------------------------------------------

test("reducer: 첫 쪽·다음 쪽(겹침 제거)·빼기(한 번만)", () => {
  let s = timelineReducer(initialTimelineState(), { type: "start", seq: 1 });
  assert.equal(s.status, "loading");
  s = timelineReducer(s, { type: "firstOk", seq: 1, page: page([photo("a1"), photo("a2")], "cur1") });
  assert.deepEqual([s.status, s.items.length, s.next], ["ready", 2, "cur1"]);
  s = timelineReducer(s, { type: "moreStart", seq: 1 });
  assert.equal(s.loadingMore, true);
  s = timelineReducer(s, { type: "moreOk", seq: 1, page: page([photo("a2"), photo("a3")], null) }); // a2 는 겹친다
  assert.deepEqual(s.items.map((i) => i.attachment_id), ["a1", "a2", "a3"]);
  assert.deepEqual([s.loadingMore, s.next], [false, null]);
  const removed = timelineReducer(s, { type: "removed", id: "a2" });
  assert.deepEqual(removed.items.map((i) => i.attachment_id), ["a1", "a3"]);
  assert.equal(timelineReducer(removed, { type: "removed", id: "a2" }), removed); // 이미 없으면 그대로
});

test("reducer: 번호(seq)가 다른 옛 응답은 모두 버린다", () => {
  const base = timelineReducer(initialTimelineState(), { type: "start", seq: 2 });
  for (const type of ["firstOk", "firstFail", "moreStart", "moreOk", "moreFail"]) {
    assert.equal(timelineReducer(base, { type, seq: 1, page: page([photo("old")]), error: { status: 503 } }), base, type);
  }
});

test("reducer: 조회 실패는 빈 목록이 아니라 오류 문구, 다음 쪽 실패는 목록을 지키고 오류만 남긴다", () => {
  let s = timelineReducer(initialTimelineState(), { type: "start", seq: 1 });
  const failed = timelineReducer(s, { type: "firstFail", seq: 1, error: { status: 503, code: "photo_checks_unavailable" } });
  assert.equal(failed.status, "error");
  assert.match(failed.error, /불러오지 못/);
  assert.equal(timelineReducer(s, { type: "firstFail", seq: 1, error: null }).error, TIMELINE_LOAD_FAILED);
  s = timelineReducer(s, { type: "firstOk", seq: 1, page: page([photo("a1")], "cur") });
  s = timelineReducer(s, { type: "moreStart", seq: 1 });
  const moreFailed = timelineReducer(s, { type: "moreFail", seq: 1, error: { status: 503, code: "photo_checks_unavailable" } });
  assert.deepEqual([moreFailed.items.length, moreFailed.loadingMore, moreFailed.next], [1, false, "cur"]);
  assert.match(moreFailed.error, /불러오지 못/);
});

test("timelineBodyKind: 보이는 사진을 모두 빼도 서버에 더 남았으면 '없어요'가 아니다", () => {
  const ready = (over) => ({ ...initialTimelineState(), status: "ready", ...over });
  assert.equal(timelineBodyKind(initialTimelineState()), "loading");
  assert.equal(timelineBodyKind({ ...initialTimelineState(), status: "error", error: "x" }), "error");
  assert.equal(timelineBodyKind(ready({ items: [photo("a1")] })), "list");
  assert.equal(timelineBodyKind(ready({ items: [], next: "cur" })), "more");
  assert.equal(timelineBodyKind(ready({ items: [], next: "cur", error: "실패" })), "more_error");
  assert.equal(timelineBodyKind(ready({ items: [], next: null })), "empty");
});

test("canLoadMoreTimeline: 준비되고 더 있고 불러오는 중이 아닐 때만", () => {
  const ready = (over) => ({ ...initialTimelineState(), status: "ready", next: "cur", ...over });
  assert.equal(canLoadMoreTimeline(ready({})), true);
  assert.equal(canLoadMoreTimeline(ready({ next: null })), false);
  assert.equal(canLoadMoreTimeline(ready({ loadingMore: true })), false);
  assert.equal(canLoadMoreTimeline({ ...initialTimelineState(), next: "cur" }), false); // 아직 로딩 중
});

// ---- 타임라인에서 빼기 흐름 ------------------------------------------------------------------

test("runExclude: 내 사진을 빼면 서버를 한 번 부르고 결과와 안내를 돌려준다", async () => {
  const calls = [];
  const working = new Set();
  const out = await runExclude({ item: photo("a1", undefined, { mine: true }), working, exclude: async (id) => calls.push(id) });
  assert.deepEqual(out, { kind: "excluded", message: EXCLUDED_NOTICE });
  assert.deepEqual(calls, ["a1"]);
  assert.equal(working.size, 0); // 끝나면 처리 중 표시를 비운다
  assert.match(EXCLUDED_NOTICE, /채팅방의 사진은 그대로/);
});

test("runExclude: 내 사진이 아니면(mine 아님) 서버를 부르지 않는다", async () => {
  let called = 0;
  for (const item of [photo("a1", undefined, { mine: false }), photo("a2", undefined, { mine: "true" }), null, undefined, { mine: true }]) {
    const out = await runExclude({ item, working: new Set(), exclude: async () => called++ });
    assert.deepEqual(out, { kind: "skipped" });
  }
  assert.equal(called, 0);
});

test("runExclude: 같은 사진을 연달아 눌러도 요청은 한 번이다", async () => {
  let release;
  const gate = new Promise((resolve) => (release = resolve));
  let calls = 0;
  const working = new Set();
  const item = photo("a1", undefined, { mine: true });
  const exclude = async () => {
    calls += 1;
    await gate;
  };
  const first = runExclude({ item, working, exclude });
  const second = await runExclude({ item, working, exclude }); // 첫 요청이 끝나기 전의 두 번째 누름
  assert.deepEqual(second, { kind: "skipped" });
  release();
  assert.equal((await first).kind, "excluded");
  assert.equal(calls, 1);
  assert.equal(working.size, 0);
});

test("runExclude: 오류별 결과 — 404·not_in_timeline 은 gone(화면에서 뺀다), 일시 오류는 failed(남겨 두고 다시 시도)", async () => {
  const run = (error) => runExclude({ item: photo("a1", undefined, { mine: true }), working: new Set(), exclude: async () => Promise.reject(error) });
  assert.equal((await run({ status: 404, code: "not_found" })).kind, "gone");
  assert.equal((await run({ status: 409, code: "not_in_timeline" })).kind, "gone");
  for (const error of [{ status: 503, code: "photo_checks_unavailable" }, { status: 429, code: "too_many_checks", retryAfter: 5 }, { code: "network_error" }]) {
    const out = await run(error);
    assert.equal(out.kind, "failed");
    assert.ok(out.message.length > 0);
  }
});

test("runExclude: 실패한 뒤에도 처리 중 표시가 남지 않아 다시 누를 수 있다", async () => {
  const working = new Set();
  const item = photo("a1", undefined, { mine: true });
  const failing = await runExclude({ item, working, exclude: async () => Promise.reject({ status: 503 }) });
  assert.equal(failing.kind, "failed");
  assert.equal(working.size, 0);
  const retry = await runExclude({ item, working, exclude: async () => ({ status: "excluded" }) });
  assert.equal(retry.kind, "excluded");
});

// ---- 서랍·마이 탭 진입 -----------------------------------------------------------------------

test("서랍: 가족 전체방에는 가족 타임라인 행이 있고 눌리면 timeline 이동이다", () => {
  const manage = buildDrawerSections({ direct: false })[0].rows;
  const row = manage.find((r) => r.key === TIMELINE_ENTRY_KEY);
  assert.ok(row);
  assert.equal(row.title, "가족 타임라인");
  assert.equal(row.state, "open");
  assert.deepEqual(resolveRowAction(row), { type: "timeline" });
  assert.deepEqual(manage.map((r) => r.key).slice(0, 3), ["pins", "media", TIMELINE_ENTRY_KEY]); // 사진 · 동영상 바로 아래
});

test("서랍: 1:1 방에는 가족 타임라인 행이 없다(가족 전체방 사진만 다룬다)", () => {
  assert.ok(!rows(buildDrawerSections({ direct: true })).some((r) => r.key === TIMELINE_ENTRY_KEY));
});

// ---- API 경로 --------------------------------------------------------------------------------

test("API listTimelinePhotos: 쿼리 모양·limit 범위·커서는 주소에 안전하게", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    return json(200, page([photo("a1")], "2026-11-16T03:00:00+00:00_12"));
  };
  const api = await import("../src/features/family-chat/api.js");
  const first = await api.listTimelinePhotos();
  await api.listTimelinePhotos({ limit: 500 });
  await api.listTimelinePhotos({ limit: 0 });
  await api.listTimelinePhotos({ limit: 5, before: "2026-11-16T03:00:00+00:00_12" });
  await api.listTimelinePhotos({ before: "" });
  assert.match(urls[0], /\/family-chat\/timeline\/photos\?limit=30$/);
  assert.match(urls[1], /\/family-chat\/timeline\/photos\?limit=60$/); // 서버 상한 60
  assert.match(urls[2], /\/family-chat\/timeline\/photos\?limit=30$/); // 0 은 서버가 받지 않아 기본값
  assert.match(urls[3], /limit=5&before=2026-11-16T03%3A00%3A00%2B00%3A00_12$/); // + 가 공백으로 읽히지 않게 인코딩
  assert.match(urls[4], /\/family-chat\/timeline\/photos\?limit=30$/); // 빈 커서는 보내지 않는다
  assert.equal(first.next_before, "2026-11-16T03:00:00+00:00_12");
});

test("API excludePhotoFromTimeline: 본문 없는 POST, 사진 id 는 주소에 안전하게", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method, body: init.body });
    return json(200, { status: "excluded", source: "manual" });
  };
  const api = await import("../src/features/family-chat/api.js");
  const out = await api.excludePhotoFromTimeline("a/b c");
  assert.deepEqual(out, { status: "excluded", source: "manual" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.match(calls[0].url, /\/family-chat\/photos\/a%2Fb%20c\/exclude$/);
  assert.equal(calls[0].body, undefined);
});

test("API excludePhotoFromTimeline: 409·404·503 은 ApiError 로 올라오고 문구로 바뀐다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  const cases = [
    [409, "not_in_timeline", /이미 타임라인에 없어요/, true],
    [404, "not_found", /확인할 수 없/, true],
    [503, "photo_checks_unavailable", /불러오지 못/, false],
  ];
  for (const [status, code, text, gone] of cases) {
    globalThis.fetch = async () => json(status, { code, message: "서버 문구" });
    await assert.rejects(
      () => api.excludePhotoFromTimeline("p1"),
      (e) => {
        assert.equal(e.status, status);
        assert.equal(e.code, code);
        assert.match(timelineErrorMessage(e), text);
        assert.equal(isGoneFromTimeline(e), gone);
        return true;
      },
    );
  }
});
