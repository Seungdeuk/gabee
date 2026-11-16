// "확인이 필요한 사진"(T05-b0-2b) 순수 함수·상태 전이·서랍 진입 조건·API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";
import {
  ACK_LABEL,
  CONFIRM_LABEL,
  REVIEW_ENTRY_KEY,
  SHEET_NOTICE_BODY,
  canConfirm,
  canLoadMoreReview,
  cellLabel,
  initialReviewState,
  isGoneError,
  photoCheckErrorMessage,
  removeItem,
  reviewBodyKind,
  reviewReducer,
  reviewRowTitle,
  runConfirm,
  runDocumentSave,
  shouldShowReviewRow,
  statusLabel,
  waitUntilRegistered,
} from "../src/features/family-chat/photoChecks.js";

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
const item = (id, status = "unsure") => ({ attachment_id: id, thumb_url: `/family-chat/photos/${id}?size=thumb`, created_at: "2026-11-14T00:00:00Z", taken_at: null, status });
const page = (ids, total = ids.length, next = null) => ({ items: ids.map((id) => item(id)), needs_review_count: total, next_before: next });
const rows = (sections) => sections.flatMap((s) => s.rows);

// ---- 문구·조건 ------------------------------------------------------------------------------

test("statusLabel: 서버 상태를 라벨로(모르는 상태도 '확인 필요')", () => {
  assert.equal(statusLabel("unsure"), "확인 필요");
  assert.equal(statusLabel("failed"), "판별 실패");
  assert.equal(statusLabel("pending"), "처리 지연");
  assert.equal(statusLabel("whatever"), "확인 필요");
  assert.equal(statusLabel(undefined), "확인 필요");
});

test("안내 문구: 타임라인 노출·문서 주의를 말하고, 촬영일을 단정하지 않는다", () => {
  assert.match(SHEET_NOTICE_BODY, /타임라인/);
  assert.match(SHEET_NOTICE_BODY, /문서/);
  assert.doesNotMatch(SHEET_NOTICE_BODY, /촬영일|찍은 날/); // 실기기 확인 전: 촬영일 단정 금지
  assert.ok(ACK_LABEL.length > 0 && CONFIRM_LABEL === "일반 사진이에요");
});

test("canConfirm: 확인란을 체크했고 처리 중이 아닐 때만 true(truthy 값으로 통과하지 않는다)", () => {
  assert.equal(canConfirm({ acknowledged: true, busy: false }), true);
  assert.equal(canConfirm({ acknowledged: false, busy: false }), false);
  assert.equal(canConfirm({ acknowledged: true, busy: true }), false);
  assert.equal(canConfirm({ acknowledged: "yes", busy: false }), false);
  assert.equal(canConfirm({ acknowledged: 1, busy: false }), false);
  assert.equal(canConfirm({}), false);
});

test("shouldShowReviewRow·reviewRowTitle: 양의 정수만 보인다", () => {
  for (const ok of [1, 2, 99]) assert.equal(shouldShowReviewRow(ok), true);
  for (const no of [0, -1, 2.5, NaN, Infinity, null, undefined, "3", "1", true]) assert.equal(shouldShowReviewRow(no), false, String(no));
  assert.equal(reviewRowTitle(3), "확인이 필요한 사진 3장");
});

test("removeItem: 한 장만 빼고 원본은 그대로", () => {
  const list = [item("a"), item("b"), item("c")];
  const out = removeItem(list, "b");
  assert.deepEqual(out.map((x) => x.attachment_id), ["a", "c"]);
  assert.equal(list.length, 3);
  assert.deepEqual(removeItem(null, "a"), []);
  assert.equal(removeItem(list, "zzz").length, 3);
});

// ---- 오류 문구 -------------------------------------------------------------------------------

test("photoCheckErrorMessage: 코드별 문구, 서버 문구·내부 사정을 그대로 보이지 않는다", () => {
  assert.match(photoCheckErrorMessage({ status: 409, code: "document_to_photo_blocked" }), /문서/);
  assert.match(photoCheckErrorMessage({ status: 409, code: "check_in_progress" }), /확인하는 중/);
  assert.match(photoCheckErrorMessage({ status: 503, code: "photo_checks_unavailable" }), /불러오지 못/);
  assert.match(photoCheckErrorMessage({ status: 404, code: "not_found" }), /확인할 수 없/);
  assert.match(photoCheckErrorMessage({ status: 404, code: "anything" }), /확인할 수 없/); // 404 는 코드와 상관없이 같은 문구(존재를 가린다)
  assert.match(photoCheckErrorMessage({ code: "network_error" }), /연결/);
  const leaked = photoCheckErrorMessage({ status: 500, code: "x", message: "SELECT * FROM chat_photo_checks 비밀" });
  assert.doesNotMatch(leaked, /SELECT|chat_photo_checks|비밀/);
  assert.equal(photoCheckErrorMessage(null), "");
});

test("photoCheckErrorMessage: 429 는 기다릴 시간을 말한다(초·분)", () => {
  assert.match(photoCheckErrorMessage({ status: 429, code: "too_many_checks", retryAfter: 30 }), /30초 뒤/);
  assert.match(photoCheckErrorMessage({ status: 429, code: "too_many_checks", retryAfter: 61 }), /2분 뒤/);
  assert.doesNotMatch(photoCheckErrorMessage({ status: 429, code: "too_many_checks" }), /뒤에 다시/);
});

test("isGoneError: 404·문서 차단만 '더 이상 대상 아님', 일시 오류는 목록에 남긴다", () => {
  assert.equal(isGoneError({ status: 404 }), true);
  assert.equal(isGoneError({ status: 409, code: "document_to_photo_blocked" }), true);
  for (const e of [{ status: 409, code: "check_in_progress" }, { status: 503 }, { status: 429 }, { code: "network_error" }, null, undefined]) {
    assert.equal(isGoneError(e), false, JSON.stringify(e));
  }
});

// ---- 목록 상태 -------------------------------------------------------------------------------

test("reviewReducer: 처음 불러오기 성공·실패, 번호가 다른 옛 응답은 버린다", () => {
  let s = reviewReducer(initialReviewState(), { type: "start", seq: 1 });
  assert.equal(s.status, "loading");
  s = reviewReducer(s, { type: "firstOk", seq: 1, page: page(["a", "b"], 5, 7) });
  assert.deepEqual([s.status, s.items.length, s.total, s.next], ["ready", 2, 5, 7]);

  const stale = reviewReducer(s, { type: "firstOk", seq: 0, page: page(["x"], 1) });
  assert.equal(stale, s); // 옛 응답은 그대로 버린다
  const restarted = reviewReducer(s, { type: "start", seq: 2 });
  assert.deepEqual([restarted.status, restarted.items.length], ["loading", 0]);
  assert.equal(reviewReducer(restarted, { type: "firstOk", seq: 1, page: page(["old"]) }), restarted); // 다시 시도 전 응답이 늦게 와도 섞이지 않는다

  const failed = reviewReducer(restarted, { type: "firstFail", seq: 2, error: { status: 503, code: "photo_checks_unavailable" } });
  assert.equal(failed.status, "error");
  assert.match(failed.error, /불러오지 못/);
  assert.equal(failed.items.length, 0); // 실패를 빈 목록(확인할 사진 없음)으로 보이지 않는다
});

test("reviewReducer: 개수를 모르는 응답이면 불러온 장수로 대신하고, 다음 쪽의 겹친 사진은 한 번만", () => {
  let s = reviewReducer(initialReviewState(), { type: "start", seq: 1 });
  s = reviewReducer(s, { type: "firstOk", seq: 1, page: { items: [item("a"), item("b")], next_before: 9 } });
  assert.equal(s.total, 2);
  s = reviewReducer(s, { type: "moreStart", seq: 1 });
  assert.equal(s.loadingMore, true);
  s = reviewReducer(s, { type: "moreOk", seq: 1, page: page(["b", "c"], 3, null) });
  assert.deepEqual(s.items.map((x) => x.attachment_id), ["a", "b", "c"]);
  assert.deepEqual([s.total, s.next, s.loadingMore], [3, null, false]);
});

test("reviewReducer: 다음 쪽 실패는 목록을 지키고 오류만 남기며, 그 상태에서도 다시 부를 수 있다", () => {
  let s = reviewReducer(initialReviewState(), { type: "start", seq: 1 });
  s = reviewReducer(s, { type: "firstOk", seq: 1, page: page(["a"], 30, 5) });
  s = reviewReducer(s, { type: "moreStart", seq: 1 });
  s = reviewReducer(s, { type: "moreFail", seq: 1, error: { code: "network_error" } });
  assert.equal(s.items.length, 1);
  assert.match(s.error, /연결/);
  assert.equal(canLoadMoreReview(s), true); // "다시 시도" 버튼은 오류가 남아 있어도 다음 쪽을 부른다
  assert.equal(canLoadMoreReview({ ...s, loadingMore: true }), false);
  assert.equal(canLoadMoreReview({ ...s, next: null }), false);
  assert.equal(canLoadMoreReview({ ...s, status: "error" }), false);
});

test("reviewReducer removed: 목록과 개수에서 한 번만 뺀다(없는 사진은 개수를 건드리지 않는다)", () => {
  let s = reviewReducer(initialReviewState(), { type: "start", seq: 1 });
  s = reviewReducer(s, { type: "firstOk", seq: 1, page: page(["a", "b"], 2) });
  s = reviewReducer(s, { type: "removed", id: "a" });
  assert.deepEqual([s.items.length, s.total], [1, 1]);
  const again = reviewReducer(s, { type: "removed", id: "a" });
  assert.equal(again, s); // 두 번째 제거는 아무 일도 없다(개수가 두 번 줄지 않는다)
  s = reviewReducer(s, { type: "removed", id: "b" });
  assert.deepEqual([s.items.length, s.total], [0, 0]);
  assert.equal(reviewReducer(s, { type: "removed", id: "b" }).total, 0); // 0 아래로 내려가지 않는다
});

test("reviewReducer: 모르는 동작은 상태를 바꾸지 않는다", () => {
  const s = initialReviewState();
  assert.equal(reviewReducer(s, { type: "nope" }), s);
});

// ---- 문서함 등록 확인 ------------------------------------------------------------------------

test("waitUntilRegistered: 등록되면 즉시 끝내고, 정해진 간격으로만 묻는다", async () => {
  const slept = [];
  const asked = [];
  const getState = async (id) => {
    asked.push(id);
    return { state: asked.length >= 2 ? "registered" : "not_registered" };
  };
  const result = await waitUntilRegistered(getState, "p1", { delays: [3000, 10000, 30000], sleep: async (ms) => slept.push(ms) });
  assert.equal(result, "registered");
  assert.deepEqual(slept, [3000, 10000]); // 두 번째에 등록 확인 → 세 번째 간격은 기다리지 않는다
  assert.deepEqual(asked, ["p1", "p1"]);
});

test("waitUntilRegistered: 끝까지 not_registered 면 등록으로 보지 않는다(성공 표시 금지)", async () => {
  const result = await waitUntilRegistered(async () => ({ state: "not_registered" }), "p1", { delays: [1, 1, 1], sleep: async () => {} });
  assert.equal(result, "not_registered");
});

test("waitUntilRegistered: 조회가 계속 실패해도 등록으로 보지 않고, 한 번 실패한 뒤 다음 간격에 다시 묻는다", async () => {
  let calls = 0;
  const flaky = async () => {
    calls += 1;
    if (calls === 1) throw new Error("boom");
    return { state: "registered" };
  };
  assert.equal(await waitUntilRegistered(flaky, "p1", { delays: [1, 1], sleep: async () => {} }), "registered");
  const dead = async () => {
    throw new Error("down");
  };
  assert.equal(await waitUntilRegistered(dead, "p1", { delays: [1, 1, 1], sleep: async () => {} }), "not_registered");
  assert.equal(await waitUntilRegistered(async () => ({}), "p1", { delays: [1], sleep: async () => {} }), "not_registered"); // 이상한 응답도 등록이 아니다
});

test("waitUntilRegistered: 화면을 떠나면(shouldStop) 더 묻지 않고 멈춘다", async () => {
  let asked = 0;
  const result = await waitUntilRegistered(
    async () => {
      asked += 1;
      return { state: "registered" };
    },
    "p1",
    { delays: [1, 1], sleep: async () => {}, shouldStop: () => true },
  );
  assert.equal(result, "stopped");
  assert.equal(asked, 0);
});

// ---- 확인 흐름(runConfirm) -------------------------------------------------------------------

test("runConfirm: 확인란을 체크하지 않았으면 서버를 부르지 않는다", async () => {
  let calls = 0;
  const working = new Set();
  const out = await runConfirm({ id: "p1", acknowledged: false, busy: null, working, confirm: async () => (calls += 1) });
  assert.deepEqual(out, { kind: "skipped" });
  assert.equal(calls, 0);
  assert.equal(working.size, 0);
});

test("runConfirm: 처리 중이거나 id 가 없거나 같은 사진이 이미 처리 중이면 부르지 않는다", async () => {
  let calls = 0;
  const confirm = async () => (calls += 1);
  assert.deepEqual(await runConfirm({ id: "p1", acknowledged: true, busy: "doc", working: new Set(), confirm }), { kind: "skipped" });
  assert.deepEqual(await runConfirm({ id: undefined, acknowledged: true, busy: null, working: new Set(), confirm }), { kind: "skipped" });
  assert.deepEqual(await runConfirm({ id: "p1", acknowledged: true, busy: null, working: new Set(["p1"]), confirm }), { kind: "skipped" });
  assert.equal(calls, 0);
});

// 중복 누름을 막지 못하면 두 번째 요청도 gate 를 기다리느라 멈추므로, 멈추지 않고 실패하도록 시간 제한을 둔다
test("runConfirm: 같은 사진을 연달아 두 번 눌러도 요청은 한 번만 나가고, 끝나면 다시 누를 수 있다", { timeout: 3000 }, async () => {
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => (release = resolve));
  const working = new Set();
  const confirm = async () => {
    calls += 1;
    await gate;
    return { status: "photo" };
  };
  const first = runConfirm({ id: "p1", acknowledged: true, busy: null, working, confirm });
  const second = runConfirm({ id: "p1", acknowledged: true, busy: null, working, confirm }); // 첫 요청이 끝나기 전의 두 번째 누름
  assert.deepEqual(await second, { kind: "skipped" });
  release();
  assert.equal((await first).kind, "confirmed");
  assert.equal(calls, 1);
  assert.equal(working.size, 0);
  assert.equal((await runConfirm({ id: "p1", acknowledged: true, busy: null, working, confirm })).kind, "confirmed"); // 끝난 뒤에는 다시 보낼 수 있다
  assert.equal(calls, 2);
});

test("runConfirm: 성공·더 이상 대상 아님(404·문서)·일시 오류를 구분하고, 오류 뒤에도 처리 중 표시를 비운다", async () => {
  const working = new Set();
  const args = (confirm) => ({ id: "p1", acknowledged: true, busy: null, working, confirm });
  const ok = await runConfirm(args(async () => ({ status: "photo", source: "manual" })));
  assert.deepEqual(ok, { kind: "confirmed", message: "일반 사진으로 확인했어요" });

  const gone404 = await runConfirm(args(async () => Promise.reject({ status: 404, code: "not_found" })));
  assert.equal(gone404.kind, "gone");
  assert.match(gone404.message, /확인할 수 없/);

  const blocked = await runConfirm(args(async () => Promise.reject({ status: 409, code: "document_to_photo_blocked" })));
  assert.equal(blocked.kind, "gone"); // 문서로 판단된 사진은 목록에서 뺀다(타임라인에 못 올린다)
  assert.match(blocked.message, /문서/);

  for (const e of [{ status: 409, code: "check_in_progress" }, { status: 503, code: "photo_checks_unavailable" }, { status: 429, code: "too_many_checks", retryAfter: 5 }, { code: "network_error" }]) {
    const out = await runConfirm(args(async () => Promise.reject(e)));
    assert.equal(out.kind, "failed", JSON.stringify(e)); // 일시 오류는 목록에 남기고 다시 시도하게 한다
    assert.ok(out.message.length > 0);
  }
  assert.equal(working.size, 0);
});

// ---- 문서로 저장 흐름(runDocumentSave) --------------------------------------------------------

const fast = { delays: [1, 1], sleep: async () => {} };

test("runDocumentSave: 저장을 시작하지 못하면 등록 확인을 하지 않고 그 문구를 돌려준다", async () => {
  let asked = 0;
  const working = new Set();
  const out = await runDocumentSave({
    id: "p1",
    busy: null,
    working,
    save: async () => ({ ok: false, message: "문서함에 저장하지 못했어요" }),
    getState: async () => {
      asked += 1;
      return { state: "registered" };
    },
    ...fast,
  });
  assert.deepEqual(out, { kind: "save_failed", message: "문서함에 저장하지 못했어요" });
  assert.equal(asked, 0);
  assert.equal(working.size, 0);
});

test("runDocumentSave: 등록이 확인돼야만 registered(성공)이고, 저장 시작 뒤 onQueued 가 한 번 불린다", async () => {
  const log = [];
  const out = await runDocumentSave({
    id: "p1",
    busy: null,
    working: new Set(),
    save: async (a) => {
      log.push(["save", a.id]);
      return { ok: true, message: "queued" };
    },
    getState: async () => {
      log.push(["state"]);
      return { state: log.filter((x) => x[0] === "state").length >= 2 ? "registered" : "not_registered" };
    },
    onQueued: () => log.push(["queued"]),
    ...fast,
  });
  assert.deepEqual(out, { kind: "registered", message: "가족 문서함에 저장됐어요" });
  assert.deepEqual(log.map((x) => x[0]), ["save", "queued", "state", "state"]);
});

test("runDocumentSave: 끝까지 등록이 안 보이면 not_registered(다시 저장 안내)이고 성공이라고 하지 않는다", async () => {
  const out = await runDocumentSave({ id: "p1", busy: null, working: new Set(), save: async () => ({ ok: true, message: "" }), getState: async () => ({ state: "not_registered" }), ...fast });
  assert.equal(out.kind, "not_registered");
  assert.match(out.message, /확인되지 않았어요/);
  assert.doesNotMatch(out.message, /저장됐어요|완료/); // 등록이 오래 걸리는 중일 수도 있어 "없다"고도, 성공이라고도 단정하지 않는다
});

test("runDocumentSave: 화면을 떠나면 stopped, 처리 중이거나 같은 사진이 진행 중이면 부르지 않는다", async () => {
  let saves = 0;
  const save = async () => {
    saves += 1;
    return { ok: true, message: "" };
  };
  const getState = async () => ({ state: "registered" });
  const stopped = await runDocumentSave({ id: "p1", busy: null, working: new Set(), save, getState, shouldStop: () => true, ...fast });
  assert.equal(stopped.kind, "stopped");
  assert.deepEqual(await runDocumentSave({ id: "p1", busy: "confirm", working: new Set(), save, getState, ...fast }), { kind: "skipped" });
  assert.deepEqual(await runDocumentSave({ id: "p1", busy: null, working: new Set(["p1"]), save, getState, ...fast }), { kind: "skipped" });
  assert.deepEqual(await runDocumentSave({ id: undefined, busy: null, working: new Set(), save, getState, ...fast }), { kind: "skipped" });
  assert.equal(saves, 1); // 첫 호출(stopped)만 저장을 시작했다
});

test("runDocumentSave: 저장이 예외를 던져도 처리 중 표시를 비운다", async () => {
  const working = new Set();
  await assert.rejects(() => runDocumentSave({ id: "p1", busy: null, working, save: async () => Promise.reject(new Error("boom")), getState: async () => ({}), ...fast }));
  assert.equal(working.size, 0);
});

// ---- 화면 상태(빈 목록 판단·칸 라벨) ----------------------------------------------------------

test("reviewBodyKind: 목록이 비어도 서버에 더 남았으면 '없어요'가 아니다(다음 쪽 조회 실패를 빈 목록으로 보이지 않는다)", () => {
  const base = initialReviewState();
  assert.equal(reviewBodyKind({ ...base, status: "loading" }), "loading");
  assert.equal(reviewBodyKind({ ...base, status: "error", error: "x" }), "error");
  assert.equal(reviewBodyKind({ ...base, status: "ready", items: [item("a")], next: 5 }), "grid");
  assert.equal(reviewBodyKind({ ...base, status: "ready", items: [], next: null }), "empty");
  assert.equal(reviewBodyKind({ ...base, status: "ready", items: [], next: 7 }), "more"); // 이어서 불러온다
  assert.equal(reviewBodyKind({ ...base, status: "ready", items: [], next: 7, error: "연결" }), "more_error"); // 오류와 다시 시도
});

test("reviewBodyKind: 다음 쪽이 실패한 뒤 보이는 사진을 모두 처리해도 빈 상태로 떨어지지 않는다(전이 이어 붙이기)", () => {
  let s = reviewReducer(initialReviewState(), { type: "start", seq: 1 });
  s = reviewReducer(s, { type: "firstOk", seq: 1, page: page(["a", "b"], 30, 9) });
  s = reviewReducer(s, { type: "moreStart", seq: 1 });
  s = reviewReducer(s, { type: "moreFail", seq: 1, error: { status: 503, code: "photo_checks_unavailable" } });
  s = reviewReducer(s, { type: "removed", id: "a" });
  s = reviewReducer(s, { type: "removed", id: "b" });
  assert.equal(s.items.length, 0);
  assert.equal(reviewBodyKind(s), "more_error");
  assert.equal(canLoadMoreReview(s), true); // 다시 시도로 이어서 불러올 수 있다
  s = reviewReducer(s, { type: "moreStart", seq: 1 });
  s = reviewReducer(s, { type: "moreOk", seq: 1, page: page(["c"], 1, null) });
  assert.equal(reviewBodyKind(s), "grid");
});

test("cellLabel: 문서함 저장을 시작한 사진은 원래 상태 대신 저장 진행을 말한다", () => {
  assert.equal(cellLabel(item("a", "unsure"), null), "확인 필요");
  assert.equal(cellLabel(item("a", "failed"), undefined), "판별 실패");
  assert.equal(cellLabel(item("a", "pending"), null), "처리 지연");
  assert.equal(cellLabel(item("a", "unsure"), "checking"), "저장 확인 중");
  assert.equal(cellLabel(item("a", "unsure"), "not_registered"), "저장 확인 필요");
});

// ---- 서랍 진입 행 ----------------------------------------------------------------------------

test("서랍: 가족 전체방에서 확인이 필요한 사진이 1장 이상이면 사진 · 동영상 바로 아래에 행이 생긴다", () => {
  const manage = buildDrawerSections({ direct: false, reviewCount: 3 })[0].rows;
  const keys = manage.map((r) => r.key);
  assert.deepEqual(keys, ["pins", "media", REVIEW_ENTRY_KEY, "familytodos"]);
  const row = manage[2];
  assert.equal(row.title, "확인이 필요한 사진 3장");
  assert.equal(row.state, "open");
  assert.deepEqual(resolveRowAction(row), { type: "photochecks" });
});

test("서랍: 0장·모름·1:1 방에서는 행이 없고, 다른 행은 그대로다", () => {
  const base = rows(buildDrawerSections({ direct: false })).map((r) => r.key);
  for (const reviewCount of [0, null, undefined, -2, 1.5, "4"]) {
    assert.deepEqual(rows(buildDrawerSections({ direct: false, reviewCount })).map((r) => r.key), base, String(reviewCount));
  }
  assert.deepEqual(rows(buildDrawerSections({ direct: true, reviewCount: 5 })).map((r) => r.key), base); // 1:1 방에는 절대 없다
  assert.ok(!base.includes(REVIEW_ENTRY_KEY));
});

// ---- API 경로 --------------------------------------------------------------------------------

test("API listMyPhotoChecks: 쿼리 모양·limit 범위·커서", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    return json(200, page(["a"], 4, 8));
  };
  const api = await import("../src/features/family-chat/api.js");
  const first = await api.listMyPhotoChecks();
  await api.listMyPhotoChecks({ limit: 500, before: 8 });
  await api.listMyPhotoChecks({ limit: 0, before: 0 });
  await api.listMyPhotoChecks({ limit: 1 });
  assert.match(urls[0], /\/family-chat\/photos\/checks\/mine\?limit=20$/);
  assert.match(urls[1], /\/family-chat\/photos\/checks\/mine\?limit=50&before=8$/); // 서버 상한 50
  assert.match(urls[2], /\/family-chat\/photos\/checks\/mine\?limit=20$/); // 0 은 서버가 받지 않아 보내지 않는다
  assert.match(urls[3], /\/family-chat\/photos\/checks\/mine\?limit=1$/);
  assert.equal(first.needs_review_count, 4);
});

test("API confirmGeneralPhoto: POST 본문은 정확히 일반 사진 확인(acknowledge true)이고, 사진 id 는 주소에 안전하게 들어간다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method, body: JSON.parse(init.body) });
    return json(200, { status: "photo", source: "manual" });
  };
  const api = await import("../src/features/family-chat/api.js");
  const out = await api.confirmGeneralPhoto("a/b c");
  assert.deepEqual(out, { status: "photo", source: "manual" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.match(calls[0].url, /\/family-chat\/photos\/a%2Fb%20c\/check$/);
  assert.deepEqual(calls[0].body, { to: "photo", reason: "uploader_confirmed_general", acknowledge: true });
});

test("API confirmGeneralPhoto: 409·404·503 은 ApiError 로 올라오고 사용자 문구로 바뀐다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  const cases = [
    [409, "document_to_photo_blocked", /문서/, true],
    [409, "check_in_progress", /확인하는 중/, false],
    [404, "not_found", /확인할 수 없/, true],
    [503, "photo_checks_unavailable", /불러오지 못/, false],
  ];
  for (const [status, code, text, gone] of cases) {
    globalThis.fetch = async () => json(status, { code, message: "서버 문구" });
    await assert.rejects(
      () => api.confirmGeneralPhoto("p1"),
      (e) => {
        assert.equal(e.status, status);
        assert.match(photoCheckErrorMessage(e), text);
        assert.equal(isGoneError(e), gone);
        return true;
      },
    );
  }
});

test("API getPhotoLibraryState: GET 경로", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method ?? "GET" });
    return json(200, { state: "registered" });
  };
  const api = await import("../src/features/family-chat/api.js");
  assert.deepEqual(await api.getPhotoLibraryState("p 1"), { state: "registered" });
  assert.match(calls[0].url, /\/family-chat\/photos\/p%201\/library$/);
  assert.equal(calls[0].method, "GET");
});
