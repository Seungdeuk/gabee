// 가족 타임라인(T05-d) 순수 함수·상태 전이·빼기 흐름·서랍 진입·API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { albumCells } from "../src/features/family-chat/album.js";
import { buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";
import {
  BUNDLE_HOLD_MS,
  EXCLUDED_NOTICE,
  SENT_DAY_NOTE,
  SINGLE_CARD_RATIO,
  TIMELINE_ENTRY_KEY,
  TIMELINE_LOAD_FAILED,
  UNKNOWN_DAY,
  buildTimelineRows,
  bundleCells,
  canExclude,
  canLoadMoreTimeline,
  initialTimelineState,
  isGoneFromTimeline,
  kstParts,
  photoCaption,
  runExclude,
  splitHeldBack,
  timelineBodyKind,
  timelineErrorMessage,
  timelineReducer,
  viewerAfterRemoval,
  viewerPhotos,
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

const ids = (row) => row.photos.map((p) => p.attachment_id).join(",");
const label = (r) => (r.type === "bundle" ? `bundle:${ids(r)}` : `${r.type}:${r.title}`);

test("buildTimelineRows: 월 머리글 → 날짜 → 묶음 카드, 날짜가 바뀔 때만 머리글, batch_id 없는 사진은 1장 카드", () => {
  const items = [
    photo("a1", "2026-11-16T03:00:00Z"),
    photo("a2", "2026-11-16T02:00:00Z"),
    photo("b1", "2026-11-10T03:00:00Z"),
    photo("c1", "2026-10-30T03:00:00Z"),
  ];
  const out = buildTimelineRows(items);
  assert.deepEqual(out.map(label), ["month:2026년 11월", "day:11월 16일", "bundle:a1", "bundle:a2", "day:11월 10일", "bundle:b1", "month:2026년 10월", "day:10월 30일", "bundle:c1"]);
  assert.equal(new Set(out.map((r) => r.key)).size, out.length); // 목록 key 가 겹치지 않는다
});

test("buildTimelineRows: 같은 batch_id 사진은 한 카드로 모이고 카드 안은 올린 순서(메시지 번호 오름차순)", () => {
  // 서버는 최신순(메시지 번호 내림차순)으로 준다. 같은 묶음 3장은 같은 날짜(display_at)다
  const at = "2026-03-01T03:00:00Z";
  const items = [photo("p13", at, { batch_id: "bat1" }), photo("p12", at, { batch_id: "bat1" }), photo("p11", at, { batch_id: "bat1" })];
  const bundles = buildTimelineRows(items).filter((r) => r.type === "bundle");
  assert.equal(bundles.length, 1);
  assert.equal(ids(bundles[0]), "p11,p12,p13");
});

test("buildTimelineRows: 사이에 다른 사진이 끼어 있어도 같은 묶음은 한 카드(카드 순서는 처음 나온 순서)", () => {
  const at = "2026-03-01T03:00:00Z";
  const items = [photo("p15", at, { batch_id: "bat1" }), photo("p14", at), photo("p13", at, { batch_id: "bat1" })];
  const out = buildTimelineRows(items).filter((r) => r.type === "bundle");
  assert.deepEqual(out.map(ids), ["p13,p15", "p14"]);
});

test("buildTimelineRows: 같은 batch_id 라도 날짜가 다르면 날짜마다 따로 카드(서로 다른 날짜 칸에 걸치지 않는다)", () => {
  const items = [photo("p21", "2026-11-16T03:00:00Z", { batch_id: "bat2" }), photo("p20", "2026-11-10T03:00:00Z", { batch_id: "bat2" })];
  const out = buildTimelineRows(items);
  assert.deepEqual(out.map(label), ["month:2026년 11월", "day:11월 16일", "bundle:p21", "day:11월 10일", "bundle:p20"]);
  assert.notEqual(out.filter((r) => r.type === "bundle")[0].key, out.filter((r) => r.type === "bundle")[1].key);
});

test("buildTimelineRows: 카드 key 는 묶음이 쪽을 넘어 자라도 그대로(batch_id 카드는 날짜+batch_id, 1장은 사진 id)", () => {
  const at = "2026-03-01T03:00:00Z";
  const first = buildTimelineRows([photo("p31", at, { batch_id: "bat3" })]).find((r) => r.type === "bundle");
  const grown = buildTimelineRows([photo("p32", at, { batch_id: "bat3" }), photo("p31", at, { batch_id: "bat3" })]).find((r) => r.type === "bundle");
  assert.equal(first.key, grown.key);
  assert.equal(buildTimelineRows([photo("solo1")]).find((r) => r.type === "bundle").key, "p-solo1");
});

test("buildTimelineRows: 입력의 모든 사진이 정확히 한 번씩만 나온다(더하거나 숨기거나 중복하지 않는다, 여러 날짜·묶음·섞임)", () => {
  const items = [];
  let n = 100;
  const days = ["2026-11-16T03:00:00Z", "2026-11-15T20:00:00Z", "2026-11-10T03:00:00Z", "2026-01-02T03:00:00Z", "깨진 값"];
  for (const day of days) for (let k = 0; k < 7; k += 1) items.push(photo(`r${n++}`, day, { batch_id: k % 3 === 0 ? null : `bt${k % 3}` }));
  const seen = buildTimelineRows(items).filter((r) => r.type === "bundle").flatMap((r) => r.photos.map((p) => p.attachment_id));
  assert.deepEqual([...seen].sort(), items.map((i) => i.attachment_id).sort());
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
  assert.deepEqual(out.filter((r) => r.type === "bundle").flatMap((r) => r.photos.map((p) => p.attachment_id)), ["a1", "z1", "z2"]);
});

test("buildTimelineRows: 빈 목록·없는 값은 빈 배열", () => {
  assert.deepEqual(buildTimelineRows([]), []);
  assert.deepEqual(buildTimelineRows(undefined), []);
});

// ---- 묶음 카드 칸 배치 -----------------------------------------------------------------------

test("bundleCells: 1장은 가로 전체 4:3 한 칸", () => {
  assert.deepEqual(bundleCells(1, 320), { cells: [{ width: 320, height: 240 }], more: 0 });
  assert.equal(SINGLE_CARD_RATIO, 0.75);
});

test("bundleCells: 2장은 나란히, 3장은 위 한 장 + 아래 두 장, 4장은 2×2", () => {
  const two = bundleCells(2, 320);
  assert.equal(two.cells.length, 2);
  assert.ok(two.cells.every((c) => c.width === c.height && c.width * 2 + 2 <= 320 + 1) && two.more === 0);
  const three = bundleCells(3, 320);
  assert.equal(three.cells.length, 3);
  assert.equal(three.cells[0].width, 320); // 위 한 장은 가로 전체
  assert.ok(three.cells[0].height < three.cells[0].width); // 가로로 긴 칸
  assert.equal(three.cells[1].width, three.cells[2].width);
  assert.equal(three.more, 0);
  const four = bundleCells(4, 320);
  assert.equal(four.cells.length, 4);
  assert.equal(four.more, 0);
});

test("bundleCells: 5장 이상은 4칸 + 남은 수 +N(10장이면 +6)", () => {
  assert.deepEqual([bundleCells(5, 320).cells.length, bundleCells(5, 320).more], [4, 1]);
  assert.deepEqual([bundleCells(10, 320).cells.length, bundleCells(10, 320).more], [4, 6]);
  assert.deepEqual(bundleCells(0, 320), { cells: [], more: 0 });
});

test("bundleCells: 2장 이상은 채팅 앨범과 같은 규칙(albumCells)이고 가로를 따른다", () => {
  for (const n of [2, 3, 4, 7]) assert.deepEqual(bundleCells(n, 250), albumCells(n, 250));
  assert.notDeepEqual(bundleCells(3, 250), bundleCells(3, 320));
});

// ---- 쪽 경계에서 묶음 분리 방지 ---------------------------------------------------------------

const at = "2026-03-01T03:00:00Z";
const inBatch = (id, batch) => photo(id, at, { batch_id: batch });

test("splitHeldBack: 더 받을 쪽이 있으면 목록 끝에 걸친 묶음만 보류한다", () => {
  const items = [photo("a1", "2026-03-02T03:00:00Z"), inBatch("p3", "bt"), inBatch("p2", "bt")];
  const { shown, held } = splitHeldBack(items, { hasMore: true });
  assert.deepEqual(shown.map((p) => p.attachment_id), ["a1"]);
  assert.deepEqual(held.map((p) => p.attachment_id), ["p3", "p2"]);
});

test("splitHeldBack: 마지막 사진이 묶음 없는 사진이면 아무것도 보류하지 않는다", () => {
  const items = [inBatch("p3", "bt"), photo("solo", at)];
  const out = splitHeldBack(items, { hasMore: true });
  assert.deepEqual([out.shown.length, out.held.length], [2, 0]);
});

test("splitHeldBack: 더 받을 쪽이 없으면(마지막 쪽) 모두 보인다", () => {
  const items = [inBatch("p3", "bt"), inBatch("p2", "bt")];
  assert.deepEqual(splitHeldBack(items, { hasMore: false }).held, []);
});

test("splitHeldBack: 다음 쪽 불러오기가 실패했거나(failed) 너무 오래 걸리면(expired) 보류하지 않고 가진 사진을 모두 보인다(무기한 숨기지 않는다)", () => {
  const items = [inBatch("p3", "bt"), inBatch("p2", "bt")];
  for (const state of [{ hasMore: true, failed: true }, { hasMore: true, expired: true }]) {
    const out = splitHeldBack(items, state);
    assert.deepEqual([out.shown.length, out.held.length], [2, 0], JSON.stringify(state));
  }
});

test("splitHeldBack: 같은 batch_id 라도 다른 날짜의 사진은 보류하지 않는다, 끼어든 같은 묶음 사진은 함께 보류한다", () => {
  const items = [photo("old", "2026-01-01T03:00:00Z", { batch_id: "bt" }), inBatch("p4", "bt"), photo("mid", at), inBatch("p2", "bt")];
  const { shown, held } = splitHeldBack(items, { hasMore: true });
  assert.deepEqual(held.map((p) => p.attachment_id), ["p4", "p2"]);
  assert.deepEqual(shown.map((p) => p.attachment_id), ["old", "mid"]);
});

test("splitHeldBack: 빈 목록과 모두 보류된 경우도 안전하다(모두 보류면 shown 이 비어 화면은 '더 불러오는 중'이 된다)", () => {
  assert.deepEqual(splitHeldBack([], { hasMore: true }), { shown: [], held: [] });
  const all = splitHeldBack([inBatch("p3", "bt"), inBatch("p2", "bt")], { hasMore: true });
  assert.deepEqual([all.shown.length, all.held.length], [0, 2]);
  const state = { ...initialTimelineState(), status: "ready", items: all.shown, next: "cur" };
  assert.equal(timelineBodyKind(state), "more"); // 다음 쪽을 이어 불러온다
});

test("쪽 경계: 갈라진 묶음은 다음 쪽이 오면 한 카드가 되고, 보류하는 동안에도 입력에 없던 사진은 나오지 않는다", () => {
  let s = timelineReducer(initialTimelineState(), { type: "start", seq: 1 });
  s = timelineReducer(s, { type: "firstOk", seq: 1, page: page([photo("t1", "2026-03-02T03:00:00Z"), inBatch("p13", "bt"), inBatch("p12", "bt")], "cur") });
  const before = buildTimelineRows(splitHeldBack(s.items, { hasMore: s.next != null }).shown).filter((r) => r.type === "bundle");
  assert.deepEqual(before.map(ids), ["t1"]); // 갈라진 묶음은 아직 그리지 않는다
  s = timelineReducer(s, { type: "moreOk", seq: 1, page: page([inBatch("p11", "bt"), photo("t0", "2026-02-01T03:00:00Z")], null) });
  const after = buildTimelineRows(splitHeldBack(s.items, { hasMore: s.next != null }).shown).filter((r) => r.type === "bundle");
  assert.deepEqual(after.map(ids), ["t1", "p11,p12,p13", "t0"]); // 묶음이 한 카드로 완성
});

test("쪽 경계: 다음 쪽 불러오기가 실패하면 보류하던 묶음도 보인다(오류 문구는 그대로 남는다)", () => {
  let s = timelineReducer(initialTimelineState(), { type: "start", seq: 1 });
  s = timelineReducer(s, { type: "firstOk", seq: 1, page: page([inBatch("p13", "bt"), inBatch("p12", "bt")], "cur") });
  s = timelineReducer(s, { type: "moreStart", seq: 1 });
  s = timelineReducer(s, { type: "moreFail", seq: 1, error: { status: 503, code: "photo_checks_unavailable" } });
  const { shown } = splitHeldBack(s.items, { hasMore: s.next != null, failed: Boolean(s.error) });
  assert.equal(buildTimelineRows(shown).filter((r) => r.type === "bundle").length, 1);
  assert.match(s.error, /불러오지 못/);
  assert.equal(BUNDLE_HOLD_MS, 8000);
});

// ---- 뷰어 연결 -------------------------------------------------------------------------------

test("viewerPhotos: 카드의 사진을 올린 순서 그대로 원본 경로와 함께 복사한다(카드가 자라도 번호가 안 밀린다)", () => {
  const bundle = { type: "bundle", key: "k", photos: [photo("p11", at), photo("a/b c", at)] };
  const out = viewerPhotos(bundle);
  assert.deepEqual(out.map((p) => p.id), ["p11", "a/b c"]);
  assert.equal(out[1].url, "/family-chat/photos/a%2Fb%20c");
  assert.equal(out[0].item, bundle.photos[0]);
  bundle.photos.push(photo("p99", at)); // 이후 카드가 자라도 이미 연 뷰어의 목록은 그대로
  assert.equal(out.length, 2);
  assert.deepEqual(viewerPhotos(undefined), []);
});

test("viewerAfterRemoval: 한 장을 빼면 남은 사진으로 이어 보고, 마지막이었으면 새 마지막, 모두 빠지면 닫는다", () => {
  const viewer = { photos: [{ id: "a" }, { id: "b" }, { id: "c" }], index: 0 };
  assert.deepEqual(viewerAfterRemoval(viewer, "b", 1), { photos: [{ id: "a" }, { id: "c" }], index: 1 }); // 지금 보던 번호에 다음 사진
  assert.deepEqual(viewerAfterRemoval(viewer, "c", 2), { photos: [{ id: "a" }, { id: "b" }], index: 1 }); // 마지막을 뺐으면 새 마지막
  assert.deepEqual(viewerAfterRemoval(viewer, "a"), { photos: [{ id: "b" }, { id: "c" }], index: 0 }); // 번호를 안 주면 viewer.index
  assert.deepEqual(viewerAfterRemoval(viewer, "zzz", 1).photos.length, 3); // 없는 사진은 목록이 그대로
  assert.equal(viewerAfterRemoval({ photos: [{ id: "a" }], index: 0 }, "a", 0), null); // 모두 빠지면 닫는다
  assert.equal(viewerAfterRemoval(null, "a"), null);
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
