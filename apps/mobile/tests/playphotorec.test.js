// 찰칵! 탐정단 가비 추천: 응답 → 화면 모양, 추천 카드로 올리기 폼, 사진 주소 허용: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { photoRecView } from "../src/features/playground/adapt.js";
import { MOCK_PHOTO_RECS } from "../src/features/playground/mock.js";
import { photoPath } from "../src/shared/photoCache.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const { createPhoto, getPhotoRecs } = await import("../src/features/playground/api.js");

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const item = { id: "r1", kind: "month", source: "album", question: "몇 월?", options: ["1월", "2월", "3월"], answer_index: 1, box_x: 0.5, box_y: 0.5, zoom: 8, image_url: "/play/photo/recommendations/r1/image" };

test("추천 응답: ok 이고 항목이 있으면 항목", () => {
  assert.deepEqual(photoRecView({ state: "ok", items: [item] }), { items: [item] });
});

test("추천 응답: ok 인데 항목이 없거나 used_up 이면 새로고침 없이 문구", () => {
  for (const recs of [{ state: "ok", items: [] }, { state: "used_up", items: [] }]) {
    const view = photoRecView(recs);
    assert.deepEqual(view.items, []);
    assert.equal(view.refresh, false);
    assert.ok(view.notice.length > 0);
  }
});

test("추천 응답: failed·preparing·cooldown 은 새로고침을 둔다", () => {
  for (const state of ["failed", "preparing", "cooldown"]) {
    const view = photoRecView({ state, items: [] });
    assert.deepEqual(view.items, []);
    assert.equal(view.refresh, true);
    assert.ok(view.notice.length > 0);
  }
});

test("추천 응답: ai_off 는 항목이 있으면 항목, 없으면 failed 처럼", () => {
  assert.deepEqual(photoRecView({ state: "ai_off", items: [item] }), { items: [item] });
  const view = photoRecView({ state: "ai_off", items: [] });
  assert.deepEqual(view.items, []);
  assert.equal(view.refresh, true);
});

test("추천 응답이 없거나 모르는 상태이면 failed 취급", () => {
  for (const recs of [null, undefined, { state: "weird", items: [item] }]) {
    const view = photoRecView(recs);
    assert.deepEqual(view.items, []);
    assert.equal(view.refresh, true);
    assert.ok(view.notice.length > 0);
  }
});

test("시안: ok 에 월·일정·흔한 사진 3개, 사진 주소는 없다", () => {
  assert.equal(MOCK_PHOTO_RECS.state, "ok");
  assert.equal(MOCK_PHOTO_RECS.items.length, 3);
  assert.deepEqual(MOCK_PHOTO_RECS.items.map((i) => i.kind).slice(0, 2), ["month", "event"]);
  assert.ok(MOCK_PHOTO_RECS.items.every((i) => !i.image_url));
  assert.ok(MOCK_PHOTO_RECS.items.some((i) => i.source === "common"));
});

test("추천 사진 주소는 허용 목록에 있다", () => {
  assert.equal(photoPath("/play/photo/recommendations/r-1/image"), "/play/photo/recommendations/r-1/image");
  assert.equal(photoPath("/play/photo/recommendations/r1/other"), null);
  assert.equal(photoPath("https://evil.test/play/photo/recommendations/r1/image"), null);
});

test("추천 받기: GET /play/photo/recommendations", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET" });
    return new Response(JSON.stringify({ state: "ok", items: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  await getPhotoRecs();
  assert.deepEqual(calls, [{ url: "http://api.test/play/photo/recommendations", method: "GET" }]);
});

test("추천 카드로 올리기: rec_id 를 넣고 파일은 붙이지 않는다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: init.body });
    return new Response(JSON.stringify({ id: "p1" }), { status: 201, headers: { "Content-Type": "application/json" } });
  };
  await createPhoto({ recId: "abc", zoom: 8, boxX: 0.25, boxY: 0.75, question: "어디서?", options: ["가", "나"], answerIndex: 1, comment: "한마디", playerIds: ["u1"] });
  const form = calls[0].body;
  assert.equal(calls[0].url, "http://api.test/play/photos");
  assert.ok(form instanceof FormData);
  assert.equal(form.get("rec_id"), "abc");
  assert.equal(form.has("file"), false);
  assert.equal(form.has("source"), false);
  assert.equal(form.get("zoom"), "8");
  assert.equal(form.get("question"), "어디서?");
  assert.deepEqual(form.getAll("options"), ["가", "나"]);
  assert.equal(form.get("answer_index"), "1");
  assert.deepEqual(form.getAll("player_ids"), ["u1"]);
});

test("recId 가 없으면 기존처럼 파일과 source 를 보낸다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ body: init.body });
    return new Response("{}", { status: 201, headers: { "Content-Type": "application/json" } });
  };
  await createPhoto({ image: { uri: "p.jpg", file: new Blob(["x"], { type: "image/jpeg" }) }, source: 2, zoom: 4, boxX: 0, boxY: 0, question: "q", options: ["a", "b"], answerIndex: 0 });
  assert.equal(calls[0].body.has("rec_id"), false);
  assert.equal(calls[0].body.has("file"), true);
  assert.equal(calls[0].body.get("source"), "2");
});
