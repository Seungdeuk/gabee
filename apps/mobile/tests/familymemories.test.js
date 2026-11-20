// 가족 추억 후보 화면(PR7)의 순수 로직 시험: 정리·제목·상태·오류(미출시 404 ≠ 빈 목록)·가족 전환 초기화·제거된 사진 반영·드로어 진입점(기본 꺼짐). npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { mockCandidatesResponse } from "../src/features/family-memory/fixtures.js";
import {
  MIN_PHOTOS,
  bodyKind,
  candidateSubtitle,
  candidateTitle,
  dateRangeLabel,
  dropPhoto,
  errorState,
  initialMemoriesState,
  memoriesReducer,
  normalizeCandidates,
  photoCaption,
  scopeKey,
  selectedCandidate,
  viewerPhotos,
} from "../src/features/family-memory/memories.js";
import { MEMORIES_ENTRY_KEY, buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";
import { memoryUiMode, memoryUiVisible } from "../src/shared/memoryFlag.js";

const photo = (id, takenAt = "2026-05-02T01:00:00+00:00", extra = {}) => ({
  attachment_id: id,
  thumb_url: `/family-chat/photos/${id}?size=thumb`,
  photo_url: `/family-chat/photos/${id}`,
  taken_at: takenAt,
  is_representative: false,
  ...extra,
});
const raw = (id, photos, extra = {}) => ({
  id,
  status: "private",
  representative: { ...photos[0], is_representative: true },
  photos,
  photo_count: photos.length,
  dated_count: photos.length,
  undated_count: 0,
  starts_at: "2026-05-02T01:00:00+00:00",
  ends_at: "2026-05-02T03:00:00+00:00",
  bridged: false,
  score: 0.8,
  algorithm_version: "memgrp-1",
  updated_at: "2026-11-19T00:00:00+00:00",
  ...extra,
});
const three = (prefix) => [photo(`${prefix}1`), photo(`${prefix}2`), photo(`${prefix}3`)];
const ok = (state, items, seq = state.seq) => memoriesReducer(state, { type: "ok", seq, items });
const loaded = (items) => {
  let s = memoriesReducer(initialMemoriesState(), { type: "scope", scope: "u1:g1", seq: 1 });
  s = memoriesReducer(s, { type: "start", seq: 2 });
  return ok(s, items, 2);
};

// ---------- 정상 렌더링에 쓰는 값 ----------
test("서버 후보를 화면용으로 정리한다: 대표 사진·사진 수·날짜 범위", () => {
  const [c] = normalizeCandidates({ items: [raw("m1", three("a"))] });
  assert.equal(c.id, "m1");
  assert.equal(c.status, "private");
  assert.equal(c.representative.attachment_id, "a1");
  assert.equal(c.photo_count, 3);
  assert.equal(c.photos.filter((p) => p.is_representative).length, 1);
  assert.equal(candidateTitle(c), "2026년 5월 2일");
  assert.equal(candidateSubtitle(c), "사진 3장");
});

test("알 수 없는 필드와 점수·알고리즘 정보는 화면 상태에 남기지 않는다", () => {
  const [c] = normalizeCandidates({ items: [raw("m1", three("a"), { secret: "x", location: "서울", people: ["지민"] })] });
  assert.deepEqual(Object.keys(c).sort(), ["dated_count", "ends_at", "id", "photo_count", "photos", "representative", "starts_at", "status", "undated_count", "updated_at"]);
  assert.ok(!JSON.stringify(c).includes("서울") && !JSON.stringify(c).includes("지민"));
});

test("제목은 촬영 날짜로만 만든다(장소·인물·감정을 짓지 않는다): 같은 날·같은 해·해가 다름·날짜 없음", () => {
  assert.equal(dateRangeLabel("2026-05-02T01:00:00+00:00", "2026-05-02T09:00:00+00:00"), "2026년 5월 2일");
  assert.equal(dateRangeLabel("2026-05-02T01:00:00+00:00", "2026-05-04T01:00:00+00:00"), "2026년 5월 2일 ~ 5월 4일");
  assert.equal(dateRangeLabel("2025-12-31T10:00:00+00:00", "2026-01-01T10:00:00+00:00"), "2025년 12월 31일 ~ 2026년 1월 1일");
  assert.equal(dateRangeLabel(null, null), null);
  assert.equal(candidateTitle({ starts_at: null, ends_at: null }), "촬영 날짜를 알 수 없어요");
  assert.ok(!/[가-힣]+(에서|와 함께|행복|즐거)/.test(candidateTitle({ starts_at: "2026-05-02T01:00:00+00:00", ends_at: "2026-05-02T01:00:00+00:00" })));
});

test("한국 시간 기준 날짜: UTC 로 전날 밤이어도 한국 날짜로 센다", () => {
  assert.equal(dateRangeLabel("2026-05-01T20:00:00+00:00", "2026-05-01T20:00:00+00:00"), "2026년 5월 2일");
});

test("촬영 날짜가 없는 사진은 날짜를 지어내지 않고 개수만 알린다", () => {
  const photos = [photo("a1"), photo("a2"), photo("a3", null), photo("a4", null)];
  const [c] = normalizeCandidates({ items: [raw("m1", photos)] });
  assert.equal(c.undated_count, 2);
  assert.equal(candidateSubtitle(c), "사진 4장 · 촬영 날짜 없는 사진 2장 포함");
  assert.equal(photoCaption(photos[2]), "촬영 날짜를 알 수 없어요");
});

test("허용되지 않은 사진 주소(외부 주소·다른 경로)는 버리고, 사진이 3장 미만이 되면 후보를 숨긴다", () => {
  const bad = [photo("a1"), photo("a2"), photo("a3", undefined, { thumb_url: "https://evil.example/x.jpg" }), photo("a4", undefined, { photo_url: "/other/path" })];
  assert.equal(normalizeCandidates({ items: [raw("m1", bad)] }).length, 0);
  assert.equal(normalizeCandidates({ items: [raw("m1", [photo("a1"), photo("a2")])] }).length, 0);
  assert.equal(MIN_PHOTOS, 3);
});

test("대표 사진이 목록에 없거나 표시가 빠져도 안전하게 첫 사진을 대표로 쓴다", () => {
  const [c] = normalizeCandidates({ items: [raw("m1", three("a"), { representative: { attachment_id: "gone" } })] });
  assert.equal(c.representative.attachment_id, "a1");
  assert.equal(c.photos.filter((p) => p.is_representative).length, 1);
});

test("잘못된 응답 모양은 빈 목록으로(앱이 죽지 않는다)", () => {
  for (const data of [null, undefined, {}, { items: "x" }, { items: [null, 1, {}] }]) assert.deepEqual(normalizeCandidates(data), []);
});

test("합성 fixture 는 같은 정리를 통과해 화면에 그려진다(개발용 mock)", () => {
  const items = normalizeCandidates(mockCandidatesResponse());
  assert.equal(items.length, 3);
  assert.ok(items.every((c) => c.photos.every((p) => p.attachment_id.startsWith("mock-"))));
  assert.equal(candidateTitle(items[0]), "2026년 5월 2일 ~ 5월 3일");
});

test("사진 뷰어 목록은 원본 주소(허용된 채팅 사진 주소)를 쓴다", () => {
  const [c] = normalizeCandidates({ items: [raw("m1", three("a"))] });
  assert.deepEqual(viewerPhotos(c).map((p) => p.url), ["/family-chat/photos/a1", "/family-chat/photos/a2", "/family-chat/photos/a3"]);
});

// ---------- 빈 목록 / 미출시 404 / 오류 ----------
test("200 + items=[] 는 정상 빈 상태이고 404(미출시)는 빈 상태가 아니다", () => {
  assert.equal(bodyKind(loaded([])), "empty");
  let s = memoriesReducer(initialMemoriesState(), { type: "scope", scope: "u1:g1", seq: 1 });
  s = memoriesReducer(s, { type: "start", seq: 2 });
  s = memoriesReducer(s, { type: "fail", seq: 2, error: { status: 404 } });
  assert.equal(bodyKind(s), "unavailable");
  assert.notEqual(bodyKind(s), "empty");
  assert.equal(s.error.retryable, false);
});

test("오류 종류: 인증 만료·권한·네트워크(재시도)·일반 오류", () => {
  assert.deepEqual(errorState({ status: 401 }), { kind: "auth", message: "로그인이 만료됐어요. 다시 로그인해 주세요", retryable: false });
  assert.equal(errorState({ status: 403 }).kind, "forbidden");
  assert.equal(errorState({ status: 0 }).kind, "network");
  assert.equal(errorState({ status: 0 }).retryable, true);
  assert.equal(errorState({ status: 500 }).kind, "error");
  assert.equal(errorState({ status: 503 }).retryable, true);
  assert.equal(errorState(null).kind, "error");
});

test("미출시·로그인 만료·권한 없음이면 받아 둔 사진도 지우지만 네트워크 오류는 같은 범위의 목록을 지우지 않는다", () => {
  const items = normalizeCandidates({ items: [raw("m1", three("a"))] });
  const withItems = loaded(items);
  for (const status of [404, 401, 403]) {
    const s = memoriesReducer(memoriesReducer(withItems, { type: "start", seq: 3 }), { type: "fail", seq: 3, error: { status } });
    assert.deepEqual(s.items, [], String(status));
    assert.notEqual(bodyKind(s), "list");
  }
  const net = memoriesReducer(memoriesReducer(withItems, { type: "start", seq: 3 }), { type: "fail", seq: 3, error: { status: 0 } });
  assert.equal(net.items.length, 1);
  assert.equal(bodyKind(net), "list"); // 받은 목록을 계속 보여 주고 새로 고침만 실패
  const first = memoriesReducer(memoriesReducer(memoriesReducer(initialMemoriesState(), { type: "scope", scope: "u1:g1", seq: 1 }), { type: "start", seq: 2 }), { type: "fail", seq: 2, error: { status: 0 } });
  assert.equal(bodyKind(first), "error");
});

test("처음 불러오는 중에는 로딩, 새로 고치는 중에는 받은 목록을 그대로 보인다", () => {
  const s = memoriesReducer(initialMemoriesState(), { type: "scope", scope: "u1:g1", seq: 1 });
  assert.equal(bodyKind(s), "loading");
  const withItems = loaded(normalizeCandidates({ items: [raw("m1", three("a"))] }));
  assert.equal(bodyKind(memoriesReducer(withItems, { type: "start", seq: 5 })), "list");
});

// ---------- 가족 전환·로그아웃·늦은 응답 ----------
test("가족이 바뀌거나 로그아웃하면 후보를 즉시 비운다(다른 가족의 후보가 남지 않는다)", () => {
  const withItems = loaded(normalizeCandidates({ items: [raw("m1", three("a"))] }));
  const other = memoriesReducer(withItems, { type: "scope", scope: "u1:g2", seq: 10 });
  assert.deepEqual(other.items, []);
  assert.equal(other.scope, "u1:g2");
  const out = memoriesReducer(withItems, { type: "scope", scope: null, seq: 11 });
  assert.deepEqual(out.items, []);
  assert.equal(out.status, "idle");
  assert.equal(memoriesReducer(withItems, { type: "scope", scope: "u1:g1", seq: 12 }), withItems); // 같은 범위면 그대로
  assert.equal(scopeKey({ id: "u1", active_group_id: "g1" }), "u1:g1");
  assert.equal(scopeKey({ id: "u1", active_group_id: null }), "u1:");
  assert.equal(scopeKey(null), null);
  assert.notEqual(scopeKey({ id: "u1", active_group_id: "g1" }), scopeKey({ id: "u1", active_group_id: "g2" }));
});

test("가족을 바꾸기 전에 보낸 응답이 늦게 와도 새 가족 화면에 들어가지 않는다", () => {
  let s = memoriesReducer(initialMemoriesState(), { type: "scope", scope: "u1:g1", seq: 1 });
  s = memoriesReducer(s, { type: "start", seq: 2 }); // 가족 1 의 요청(번호 2)
  s = memoriesReducer(s, { type: "scope", scope: "u1:g2", seq: 3 }); // 가족 2 로 전환
  s = memoriesReducer(s, { type: "start", seq: 4 });
  const stale = ok(s, normalizeCandidates({ items: [raw("old", three("x"))] }), 2);
  assert.deepEqual(stale.items, []);
  assert.equal(memoriesReducer(s, { type: "fail", seq: 2, error: { status: 404 } }).status, "loading"); // 늦은 오류도 무시
  const fresh = ok(s, normalizeCandidates({ items: [raw("new", three("y"))] }), 4);
  assert.deepEqual(fresh.items.map((c) => c.id), ["new"]);
});

// ---------- 삭제·철회·제외 후 새로 고침 / 사진 로딩 실패 ----------
test("새로 고침 응답이 목록을 통째로 바꾼다: 서버가 뺀 사진·후보는 바로 사라진다", () => {
  const before = loaded(normalizeCandidates({ items: [raw("m1", [...three("a"), photo("a4")]), raw("m2", three("b"))] }));
  assert.equal(before.items.length, 2);
  const after = ok(memoriesReducer(before, { type: "start", seq: 9 }), normalizeCandidates({ items: [raw("m1", three("a"))] }), 9);
  assert.deepEqual(after.items.map((c) => [c.id, c.photo_count]), [["m1", 3]]);
  assert.ok(!JSON.stringify(after).includes("a4"));
  assert.equal(selectedCandidate(after.items, "m2"), null); // 상세를 보던 후보가 사라지면 null → 화면이 닫는다
  assert.equal(selectedCandidate(after.items, null), null);
  assert.equal(selectedCandidate(after.items, "m1").id, "m1");
});

test("사진이 더는 열리지 않으면(이미지 로딩 실패) 그 사진을 빼고 날짜 범위를 다시 계산하며 3장 미만이면 후보를 숨긴다", () => {
  const photos = [photo("a1", "2026-05-02T01:00:00+00:00"), photo("a2", "2026-05-03T01:00:00+00:00"), photo("a3", "2026-05-04T01:00:00+00:00"), photo("a4", "2026-05-05T01:00:00+00:00")];
  const state = loaded(normalizeCandidates({ items: [raw("m1", photos, { starts_at: "2026-05-02T01:00:00+00:00", ends_at: "2026-05-05T01:00:00+00:00" })] }));
  const one = memoriesReducer(state, { type: "photoGone", candidateId: "m1", attachmentId: "a4" });
  assert.equal(one.items[0].photo_count, 3);
  assert.equal(one.items[0].ends_at, "2026-05-04T01:00:00+00:00"); // 빠진 사진의 날짜가 범위에 남지 않는다
  assert.ok(!JSON.stringify(one).includes("a4"));
  const rep = memoriesReducer(state, { type: "photoGone", candidateId: "m1", attachmentId: state.items[0].representative.attachment_id });
  assert.notEqual(rep.items[0].representative.attachment_id, state.items[0].representative.attachment_id);
  assert.equal(rep.items[0].photos.filter((p) => p.is_representative).length, 1);
  const two = memoriesReducer(one, { type: "photoGone", candidateId: "m1", attachmentId: "a3" });
  assert.deepEqual(two.items, []);
  assert.equal(memoriesReducer(state, { type: "photoGone", candidateId: "none", attachmentId: "a1" }).items.length, 1);
  assert.equal(dropPhoto(state.items[0], "nope"), state.items[0]);
});

// ---------- 기능 노출 스위치(기본 꺼짐) ----------
test("추억 화면 노출 스위치는 기본 꺼짐이고 on·mock 만 켜진다", () => {
  assert.equal(memoryUiMode(undefined), "off");
  assert.equal(memoryUiMode(""), "off");
  assert.equal(memoryUiMode("true"), "off");
  assert.equal(memoryUiMode(" ON "), "on");
  assert.equal(memoryUiMode("mock"), "mock");
  assert.equal(memoryUiVisible("off"), false);
  assert.equal(memoryUiVisible("on"), true);
  assert.equal(memoryUiVisible("mock"), true);
});

test("서랍: 기본에서는 추억 줄이 없고(기존 서랍과 같다) 개발 스위치가 켜졌을 때만 가족방에 생긴다", () => {
  const base = buildDrawerSections({ direct: false, pinsReady: true, muted: false, reviewCount: null });
  const explicitOff = buildDrawerSections({ direct: false, pinsReady: true, muted: false, reviewCount: null, memoryUi: false });
  assert.deepEqual(base, explicitOff);
  assert.ok(!base.flatMap((s) => s.rows).some((r) => r.key === MEMORIES_ENTRY_KEY));
  const on = buildDrawerSections({ direct: false, pinsReady: true, muted: false, reviewCount: null, memoryUi: true });
  const rows = on[0].rows;
  const at = rows.findIndex((r) => r.key === MEMORIES_ENTRY_KEY);
  assert.ok(at > 0 && rows[at - 1].key === "timeline", "타임라인 바로 아래");
  assert.deepEqual(resolveRowAction(rows[at]), { type: "memories" });
  assert.equal(on[0].rows.length, base[0].rows.length + 1);
  const direct = buildDrawerSections({ direct: true, pinsReady: true, muted: false, memoryUi: true });
  assert.ok(!direct.flatMap((s) => s.rows).some((r) => r.key === MEMORIES_ENTRY_KEY), "1:1 방에는 없다");
});
