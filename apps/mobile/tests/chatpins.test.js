// 고정 메시지(공지) 순수 함수·API 경로·서랍 행을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { pinErrorMessage } from "../src/features/family-chat/chatUtils.js";
import { buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";
import {
  ALREADY_PINNED_NOTICE,
  MAX_PINS,
  REPLACED_NOTICE,
  applyPinResult,
  BUSY_NOTICE,
  bubbleSelectable,
  bubbleTextStyle,
  failureEffect,
  pinSettled,
  canPin,
  pinTapAction,
  reloadGate,
  initialPinsState,
  nextPinPollDelay,
  normalizePins,
  optimisticPin,
  optimisticUnpin,
  pinA11yLabel,
  pinBarView,
  pinLine,
  pinMeta,
  pinResultNotice,
  pinsReducer,
  normalizePin,
  setPinHidden,
} from "../src/features/family-chat/pinUtils.js";

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
const pin = (id, at, extra = {}) => ({
  message_id: id,
  text: `공지 ${id}`,
  text_truncated: false,
  user_id: "mom",
  user_name: "엄마",
  created_at: "2026-10-24T01:00:00Z",
  pinned_by: "dad",
  pinned_by_name: "아빠",
  pinned_at: at,
  ...extra,
});
const msg = (id, extra = {}) => ({ id, user_id: "mom", user_name: "엄마", text: `글 ${id}`, created_at: "2026-10-24T01:00:00Z", ...extra });
const me = { id: "me", name: "지민" };
const ids = (pins) => pins.map((p) => p.message_id);

test("canPin: 서버에 저장된 텍스트 메시지만(사진·빈 글·임시·실패 제외)", () => {
  assert.equal(canPin(msg(5)), true);
  assert.equal(canPin(msg(5, { attachment: { id: "a", kind: "image" } })), false); // 사진 메시지(글이 있어도)
  assert.equal(canPin(msg(5, { text: "" })), false);
  assert.equal(canPin(msg(5, { text: "   \n" })), false);
  assert.equal(canPin(msg("tmp-1", { clientId: "tmp-1", status: "sending" })), false);
  assert.equal(canPin(msg("tmp-2", { clientId: "tmp-2", status: "failed" })), false);
  assert.equal(canPin(msg(5, { status: "failed" })), false);
  assert.equal(canPin(msg(0)), false);
  assert.equal(canPin(null), false);
});

test("normalizePins: 최신순·최대 2개·중복 제거·이상한 항목 버림", () => {
  const list = [pin(1, "2026-10-24T01:00:00Z"), pin(3, "2026-10-24T03:00:00Z"), pin(2, "2026-10-24T02:00:00Z"), { message_id: "x" }, null];
  assert.equal(MAX_PINS, 2);
  assert.deepEqual(ids(normalizePins(list)), [3, 2]);
  assert.deepEqual(ids(normalizePins([pin(1, "2026-10-24T01:00:00Z"), pin(1, "2026-10-24T02:00:00Z")])), [1]);
  assert.deepEqual(normalizePins(undefined), []);
  assert.deepEqual(normalizePins({ items: [] }), []);
  assert.equal(normalizePins([pin(1, "2026-10-24T01:00:00Z", { text: undefined })]).length, 0); // 본문 없는 항목은 지어내지 않는다
});

test("optimisticPin: 추가·이미 있으면 그대로·3번째는 가장 오래된 것이 빠진다", () => {
  const base = [pin(1, "2026-10-24T01:00:00Z"), pin(2, "2026-10-24T02:00:00Z")];
  const one = optimisticPin([], msg(7, { text: "x".repeat(250) }), me, "2026-10-24T05:00:00Z");
  assert.deepEqual(ids(one.pins), [7]);
  assert.equal(one.pins[0].text.length, 200);
  assert.equal(one.pins[0].text_truncated, true);
  assert.equal(one.pins[0].pinned_by, "me");
  assert.equal(one.replacedId, null);
  const dup = optimisticPin(base, msg(1), me, "2026-10-24T05:00:00Z");
  assert.deepEqual(ids(dup.pins), [2, 1]);
  assert.equal(dup.replacedId, null);
  const third = optimisticPin(base, msg(9), me, "2026-10-24T05:00:00Z");
  assert.deepEqual(ids(third.pins), [9, 2]);
  assert.equal(third.replacedId, 1);
});

test("optimisticUnpin·applyPinResult: 해제, replaced_message_id 처리, 2개 초과 정리", () => {
  const base = [pin(2, "2026-10-24T02:00:00Z"), pin(1, "2026-10-24T01:00:00Z")];
  assert.deepEqual(ids(optimisticUnpin(base, 2)), [1]);
  assert.deepEqual(ids(optimisticUnpin(base, "1")), [2]);
  assert.deepEqual(ids(optimisticUnpin(base, 99)), [2, 1]);
  const result = { item: pin(9, "2026-10-24T05:00:00Z"), replaced_message_id: 1, already_pinned: false };
  assert.deepEqual(ids(applyPinResult(base, result)), [9, 2]);
  // 서버가 replaced 를 알려 주지 않아도 2개를 넘기지 않는다
  assert.deepEqual(ids(applyPinResult(base, { item: pin(9, "2026-10-24T05:00:00Z"), replaced_message_id: null, already_pinned: false })), [9, 2]);
  // 이미 고정된 메시지: 중복 없이 서버 항목으로 갱신
  assert.deepEqual(ids(applyPinResult(base, { item: pin(2, "2026-10-24T02:00:00Z"), replaced_message_id: null, already_pinned: true })), [2, 1]);
});

test("pinResultNotice: 교체·이미 고정·일반", () => {
  assert.equal(REPLACED_NOTICE, "가장 오래된 공지가 내려갔어요");
  assert.match(pinResultNotice({ replaced_message_id: 1, already_pinned: false }), /가장 오래된 공지가 내려갔어요/);
  assert.equal(pinResultNotice({ replaced_message_id: null, already_pinned: true }), ALREADY_PINNED_NOTICE);
  assert.equal(pinResultNotice({ replaced_message_id: null, already_pinned: false }), "게시판에 올렸어요");
});

test("pinsReducer: 낙관적 고정 → 실패 되돌리기, 오래된 조회 응답은 버린다", () => {
  const start = pinsReducer(initialPinsState, { type: "loaded", seq: 1, items: [pin(1, "2026-10-24T01:00:00Z")] });
  assert.deepEqual(ids(start.items), [1]);
  const before = start.items;
  const optimistic = pinsReducer(start, { type: "pin", seq: 3, message: msg(5), me, now: "2026-10-24T05:00:00Z" });
  assert.deepEqual(ids(optimistic.items), [5, 1]);
  // 고정을 누르기 전(seq 2)에 시작한 조회 응답은 낙관적 상태를 덮지 못한다
  assert.equal(pinsReducer(optimistic, { type: "loaded", seq: 2, items: [] }), optimistic);
  const reverted = pinsReducer(optimistic, { type: "revert_pin", seq: 4, messageId: 5, restore: null });
  assert.deepEqual(ids(reverted.items), [1]);
  assert.equal(pinsReducer(reverted, { type: "loaded", seq: 3, items: [] }).items.length, 1); // 되돌린 뒤에도 그 전 응답은 버림
  assert.deepEqual(ids(pinsReducer(reverted, { type: "loaded", seq: 5, items: [pin(8, "2026-10-24T08:00:00Z")] }).items), [8]);
  const confirmed = pinsReducer(optimistic, { type: "confirmed", seq: 4, result: { item: pin(5, "2026-10-24T05:00:00Z"), replaced_message_id: null, already_pinned: false } });
  assert.deepEqual(ids(confirmed.items), [5, 1]);
  const unpinned = pinsReducer(confirmed, { type: "unpin", seq: 6, messageId: 5 });
  assert.deepEqual(ids(unpinned.items), [1]);
  assert.equal(pinsReducer(unpinned, { type: "nope", seq: 7 }), unpinned);
});

test("pinBarView: 펼치면 2개, 접으면 가장 최근 1개, 토글은 2개일 때만", () => {
  const two = [pin(1, "2026-10-24T01:00:00Z"), pin(2, "2026-10-24T02:00:00Z")];
  assert.deepEqual(ids(pinBarView(two, true).rows), [2, 1]);
  assert.deepEqual(ids(pinBarView(two, false).rows), [2]);
  assert.equal(pinBarView(two, false).hidden, 1);
  assert.equal(pinBarView(two, true).canToggle, true);
  assert.equal(pinBarView([two[0]], false).canToggle, false);
  assert.deepEqual(pinBarView([], true).rows, []);
});

test("pinLine·pinMeta·pinA11yLabel: 한 줄 본문, 올린 사람·시각, 별명 우선", () => {
  const p = pin(2, "2026-10-24T06:20:00Z", { text: "토요일\n  저녁   7시" }); // 한국 시간 15:20
  assert.equal(pinLine(p), "토요일 저녁 7시");
  assert.match(pinMeta(p), /^아빠 올림 · 10월 24일 /);
  assert.match(pinMeta(p, (id) => (id === "dad" ? "우리 아빠" : undefined)), /^우리 아빠 올림/);
  assert.match(pinA11yLabel(p), /엄마: 토요일 저녁 7시/);
  assert.equal(pinMeta({ pinned_at: "모름" }), "가족 올림");
});

test("nextPinPollDelay: 정상 30초, 실패마다 두 배로 최대 2분", () => {
  assert.equal(nextPinPollDelay(0), 30000);
  assert.equal(nextPinPollDelay(1), 60000);
  assert.equal(nextPinPollDelay(2), 120000);
  assert.equal(nextPinPollDelay(9), 120000);
});

test("pinErrorMessage: not_pinnable·invalid_message·404·429, 해제 중 404, 그 밖에는 공통 문구", () => {
  assert.equal(pinErrorMessage({ status: 400, code: "not_pinnable" }), "사진이나 빈 메시지는 게시판에 올릴 수 없어요");
  assert.match(pinErrorMessage({ status: 400, code: "invalid_message" }), /이 대화방의 메시지가 아니라/);
  assert.equal(pinErrorMessage({ status: 429, code: "rate_limited" }), "너무 자주 바꿨어요. 잠시 뒤에 다시 해 주세요");
  assert.equal(pinErrorMessage({ status: 404, code: "not_found" }), "대화방을 찾을 수 없거나 권한이 없어요");
  assert.equal(pinErrorMessage({ status: 404 }, "unpin"), "이미 내려간 공지예요");
  assert.equal(pinErrorMessage({ status: 0, code: "network_error" }), "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요");
  assert.equal(pinErrorMessage(null), "잠시 문제가 생겼어요. 다시 시도해 주세요");
});

test("API listPins·pinMessage·unpinMessage: 경로·메서드·본문", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    if (init.method === "DELETE") return new Response(null, { status: 204 });
    return json(200, init.method === "POST" ? { item: pin(5, "2026-10-24T05:00:00Z"), replaced_message_id: null, already_pinned: false } : { items: [] });
  };
  const api = await import("../src/features/family-chat/api.js");

  await api.listPins();
  await api.listPins({ roomId: "r 1" });
  const posted = await api.pinMessage({ messageId: 5 });
  await api.pinMessage({ roomId: "r1", messageId: "6" });
  const removed = await api.unpinMessage({ messageId: 5 });
  await api.unpinMessage({ roomId: "r1", messageId: 6 });

  assert.match(calls[0].url, /\/family-chat\/pins$/);
  assert.equal(calls[0].method, "GET");
  assert.match(calls[1].url, /\/family-chat\/pins\?room_id=r%201$/);
  assert.equal(calls[2].method, "POST");
  assert.match(calls[2].url, /\/family-chat\/pins$/);
  assert.deepEqual(JSON.parse(calls[2].body), { message_id: 5 }); // 가족 전체방은 room_id 를 보내지 않는다
  assert.deepEqual(JSON.parse(calls[3].body), { room_id: "r1", message_id: 6 });
  assert.equal(posted.item.message_id, 5);
  assert.equal(calls[4].method, "DELETE");
  assert.match(calls[4].url, /\/family-chat\/pins\/5$/);
  assert.match(calls[5].url, /\/family-chat\/pins\/6\?room_id=r1$/);
  assert.equal(removed, null);
});

test("API pinMessage: 400 not_pinnable·429 는 ApiError 로 올라와 문구가 된다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  for (const [status, code, text] of [
    [400, "not_pinnable", "사진이나 빈 메시지는 게시판에 올릴 수 없어요"],
    [429, "rate_limited", "너무 자주 바꿨어요. 잠시 뒤에 다시 해 주세요"],
  ]) {
    globalThis.fetch = async () => json(status, { code, message: "m" });
    await assert.rejects(
      () => api.pinMessage({ messageId: 5 }),
      (e) => {
        assert.equal(e.status, status);
        assert.equal(pinErrorMessage(e), text);
        return true;
      },
    );
  }
});

test("서랍: 게시판 행은 연결되면 동작 행이고 가족방·1:1 모두 같다", () => {
  const find = (sections, key) => sections.flatMap((s) => s.rows).find((r) => r.key === key);
  for (const direct of [false, true]) {
    const row = find(buildDrawerSections({ direct, pinsReady: true }), "pins");
    assert.equal(row.state, "open");
    assert.equal(row.subtitle, "공지 모아보기");
    assert.deepEqual(resolveRowAction(row), { type: "pins" });
    assert.equal(find(buildDrawerSections({ direct }), "pins").state, "soon"); // 연결 전에는 이전처럼 준비 중
  }
  // 다른 행은 그대로
  const soon = buildDrawerSections({ direct: false, pinsReady: true }).flatMap((s) => s.rows).filter((r) => r.state === "soon").map((r) => r.key);
  assert.deepEqual(soon, ["search", "docs", "todos", "notifications", "privacy", "edit"]);
});

test("겹치는 요청: A 고정 대기 중 X 해제 성공 → A 실패해도 X 는 되살아나지 않는다", () => {
  let st = pinsReducer(initialPinsState, { type: "loaded", seq: 1, items: [pin(1, "2026-10-24T01:00:00Z"), pin(2, "2026-10-24T02:00:00Z")] });
  const evicted = st.items.find((p) => p.message_id === 1);
  st = pinsReducer(st, { type: "pin", seq: 2, message: msg(9), me, now: "2026-10-24T05:00:00Z" }); // A=9 고정, 1 이 밀려남
  assert.deepEqual(ids(st.items), [9, 2]);
  st = pinsReducer(st, { type: "unpin", seq: 3, messageId: 2 }); // X=2 해제 성공(되돌리지 않음)
  assert.deepEqual(ids(st.items), [9]);
  st = pinsReducer(st, { type: "revert_pin", seq: 4, messageId: 9, restore: evicted }); // A 실패
  assert.deepEqual(ids(st.items), [1]); // 2 는 해제된 채, 밀려났던 1 만 복원
});

test("겹치는 요청: A 고정 → B 고정 → 둘 다 실패하면 원래 목록으로", () => {
  const base = [pin(1, "2026-10-24T01:00:00Z"), pin(2, "2026-10-24T02:00:00Z")];
  let st = pinsReducer(initialPinsState, { type: "loaded", seq: 1, items: base });
  const a = optimisticPin(st.items, msg(8), me, "2026-10-24T05:00:00Z");
  const restoreA = st.items.find((p) => p.message_id === a.replacedId);
  st = pinsReducer(st, { type: "pin", seq: 2, message: msg(8), me, now: "2026-10-24T05:00:00Z" });
  const b = optimisticPin(st.items, msg(9), me, "2026-10-24T06:00:00Z");
  const restoreB = st.items.find((p) => p.message_id === b.replacedId);
  st = pinsReducer(st, { type: "pin", seq: 3, message: msg(9), me, now: "2026-10-24T06:00:00Z" });
  assert.deepEqual(ids(st.items), [9, 8]);
  st = pinsReducer(st, { type: "revert_pin", seq: 4, messageId: 9, restore: restoreB }); // B 실패
  st = pinsReducer(st, { type: "revert_pin", seq: 5, messageId: 8, restore: restoreA }); // A 실패
  assert.deepEqual(ids(st.items), [2, 1]);
});

test("해제 실패는 그 항목만 되살리고, 폴링이 먼저 시작했어도 낙관적 상태를 덮지 못한다", () => {
  const base = [pin(1, "2026-10-24T01:00:00Z"), pin(2, "2026-10-24T02:00:00Z")];
  let st = pinsReducer(initialPinsState, { type: "loaded", seq: 1, items: base });
  st = pinsReducer(st, { type: "unpin", seq: 3, messageId: 2 });
  assert.equal(pinsReducer(st, { type: "loaded", seq: 2, items: base }), st); // 해제 직전에 시작한 조회
  st = pinsReducer(st, { type: "revert_unpin", seq: 4, item: base[1] });
  assert.deepEqual(ids(st.items), [2, 1]);
});

test("optimisticPin: 기기 시계가 서버보다 늦어도 새 고정이 맨 앞", () => {
  const base = [pin(1, "2026-10-24T09:00:00Z")];
  const r = optimisticPin(base, msg(5), me, "2026-10-24T01:00:00Z"); // 기기 시각이 더 과거
  assert.deepEqual(ids(r.pins), [5, 1]);
  const full = optimisticPin([pin(1, "2026-10-24T09:00:00Z"), pin(2, "2026-10-24T09:30:00Z")], msg(5), me, "2026-10-24T01:00:00Z");
  assert.deepEqual(ids(full.pins), [5, 2]); // 새 고정이 잘리지 않고 가장 오래된 1 이 밀린다
  assert.equal(full.replacedId, 1);
});

test("pinTapAction: 라이브이고 목록에 있으면 scroll, 없거나 과거 창이면 focus", () => {
  const list = [msg(3), msg("tmp-1", { clientId: "tmp-1", status: "sending" })];
  assert.equal(pinTapAction({ messages: list, messageId: 3, focusing: false }), "scroll");
  assert.equal(pinTapAction({ messages: list, messageId: "3", focusing: false }), "scroll");
  assert.equal(pinTapAction({ messages: list, messageId: 4, focusing: false }), "focus");
  assert.equal(pinTapAction({ messages: list, messageId: 3, focusing: true }), "focus");
});

test("bubbleSelectable: 메뉴가 있는 네이티브만 선택을 끈다", () => {
  assert.equal(bubbleSelectable({ canAct: true, os: "ios" }), false);
  assert.equal(bubbleSelectable({ canAct: true, os: "android" }), false);
  assert.equal(bubbleSelectable({ canAct: true, os: "web" }), true);
  assert.equal(bubbleSelectable({ canAct: false, os: "ios" }), true);
  assert.equal(BUSY_NOTICE, "처리 중이에요");
});

test("reloadGate: 조회 중 요청은 끝난 뒤 한 번 더, 겹쳐 여러 번 불러도 한 번만", () => {
  const free = { inFlight: false, again: false };
  const first = reloadGate(free, "request");
  assert.equal(first.run, true);
  const second = reloadGate(first.gate, "request");
  assert.equal(second.run, false);
  const third = reloadGate(second.gate, "request");
  const done = reloadGate(third.gate, "done");
  assert.equal(done.run, true);
  assert.deepEqual(done.gate, free);
  assert.equal(reloadGate(reloadGate(free, "request").gate, "done").run, false); // 겹침이 없었으면 다시 하지 않는다
});

test("bubbleTextStyle: 선택을 끄면 noSelect 가 base 의 userSelect 를 덮고, 켜면 base 값이 남는다", () => {
  const base = { fontSize: 15, userSelect: "text" };
  const noSelect = { userSelect: "none" };
  const photo = { padding: 4 };
  const flat = (list) => Object.assign({}, ...list);
  assert.equal(flat(bubbleTextStyle({ selectable: false, base, noSelect })).userSelect, "none");
  assert.equal(flat(bubbleTextStyle({ selectable: true, base, noSelect })).userSelect, "text");
  const withPhoto = flat(bubbleTextStyle({ selectable: false, base, photo, noSelect }));
  assert.equal(withPhoto.userSelect, "none");
  assert.equal(withPhoto.padding, 4);
  assert.equal(withPhoto.fontSize, 15);
});

test("pinErrorMessage: 409 pin_changed", () => {
  const text = "다른 사람이 방금 바꿨어요. 다시 확인해 주세요";
  assert.equal(pinErrorMessage({ status: 409, code: "pin_changed" }), text);
  assert.equal(pinErrorMessage({ status: 409 }, "unpin"), text);
});

test("failureEffect·pinSettled: 해제 404 는 그대로 두고, 요청 중이거나 화면이 사라졌으면 조회를 반영·재조회하지 않는다", () => {
  assert.equal(failureEffect("unpin", { status: 404 }), "keep");
  assert.equal(failureEffect("pin", { status: 404 }), "revert");
  assert.equal(failureEffect("unpin", { status: 500 }), "revert");
  assert.equal(failureEffect("unpin", null), "revert");
  assert.equal(pinSettled({ pending: 0, alive: true }), true);
  assert.equal(pinSettled({ pending: 1, alive: true }), false); // 요청 중에 온 조회 응답은 버린다
  assert.equal(pinSettled({ pending: 0, alive: false }), false);
  // 마지막 요청이 끝났을 때만(pending 이 0 이 될 때) 서버 맞춤 조회
  assert.deepEqual([2, 1, 0].map((pending) => pinSettled({ pending, alive: true })), [false, false, true]);
});

// ── 게시판(8-b): 원본 삭제 표시, 나만 숨기기 ───────────────────────────

test("normalizePin: message_deleted·hidden 을 불리언으로 다듬고 없으면 false", () => {
  const base = { message_id: 7, text: "공지", pinned_at: "2026-10-24T01:00:00Z" };
  assert.equal(normalizePin(base).message_deleted, false);
  assert.equal(normalizePin(base).hidden, false);
  assert.equal(normalizePin({ ...base, message_deleted: true, hidden: true }).message_deleted, true);
  assert.equal(normalizePin({ ...base, hidden: "yes" }).hidden, true);
});

test("pinBarView: 내가 숨긴 공지는 줄에서 빼고 개수만 알려 준다, 토글은 보이는 공지가 2개일 때만", () => {
  const a = { ...pin(1, "2026-10-24T01:00:00Z"), hidden: true };
  const b = pin(2, "2026-10-24T02:00:00Z");
  const c = pin(3, "2026-10-24T03:00:00Z");
  const onlyHidden = pinBarView([a], true);
  assert.deepEqual([onlyHidden.rows.length, onlyHidden.hiddenByMe, onlyHidden.canToggle], [0, 1, false]);
  const mixed = pinBarView([a, b], true);
  assert.deepEqual(mixed.rows.map((r) => r.message_id), [2]);
  assert.equal(mixed.hiddenByMe, 1);
  assert.equal(mixed.canToggle, false); // 보이는 공지가 1개
  const two = pinBarView([b, c], false);
  assert.deepEqual(two.rows.map((r) => r.message_id), [3]);
  assert.deepEqual([two.canToggle, two.hidden, two.hiddenByMe], [true, 1, 0]);
});

test("setPinHidden·pinsReducer set_hidden: 한 공지만 바꾸고 되돌리면 원래 값, 없는 공지는 그대로", () => {
  const items = [pin(1, "2026-10-24T01:00:00Z"), pin(2, "2026-10-24T02:00:00Z")];
  const hidden = setPinHidden(items, 1, true);
  assert.deepEqual(hidden.map((p) => [p.message_id, p.hidden]), [[2, false], [1, true]]);
  assert.deepEqual(setPinHidden(hidden, 1, false).map((p) => p.hidden), [false, false]);
  assert.deepEqual(setPinHidden(items, 99, true).map((p) => p.hidden), [false, false]);
  let st = { items, mutSeq: 0 };
  st = pinsReducer(st, { type: "set_hidden", seq: 1, messageId: 2, hidden: true });
  assert.equal(st.items.find((p) => p.message_id === 2).hidden, true);
  assert.equal(st.mutSeq, 1);
  // 오래된 조회 응답은 방금 숨긴 상태를 덮지 못한다
  assert.equal(pinsReducer(st, { type: "loaded", seq: 0, items }).items.find((p) => p.message_id === 2).hidden, true);
});

test("pinMeta·pinA11yLabel: 원본이 지워진 공지는 표시를 붙인다", () => {
  const p = { ...pin(2, "2026-10-24T06:20:00Z"), message_deleted: true };
  assert.match(pinMeta(p), / · 원본 삭제됨$/);
  assert.match(pinA11yLabel(p), /원본 메시지는 삭제됐어요/);
  assert.doesNotMatch(pinMeta(pin(3, "2026-10-24T06:20:00Z")), /원본 삭제됨/);
});

test("failureEffect·pinErrorMessage: 숨기기·되돌리기 중 404(이미 내려감)는 그대로 두고 안내한다", () => {
  for (const action of ["unpin", "hide", "show"]) assert.equal(failureEffect(action, { status: 404 }), "keep");
  assert.equal(failureEffect("pin", { status: 404 }), "revert");
  assert.equal(failureEffect("hide", { status: 500 }), "revert");
  assert.equal(pinErrorMessage({ status: 404 }, "hide"), "이미 내려간 공지예요");
  assert.equal(pinErrorMessage({ status: 404 }, "show"), "이미 내려간 공지예요");
});

test("API hidePin·showPin: 경로·메서드(PUT/DELETE), 방 id 는 쿼리", async () => {
  const calls2 = [];
  globalThis.fetch = async (url, init) => {
    calls2.push({ url: String(url), method: init?.method ?? "GET" });
    return json(200, { message_id: 5, hidden: true });
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.hidePin({ messageId: 5 });
  await api.showPin({ roomId: "r1", messageId: 5 });
  assert.match(calls2[0].url, /\/family-chat\/pins\/5\/hide$/);
  assert.equal(calls2[0].method, "PUT");
  assert.match(calls2[1].url, /\/family-chat\/pins\/5\/hide\?room_id=r1$/);
  assert.equal(calls2[1].method, "DELETE");
});
