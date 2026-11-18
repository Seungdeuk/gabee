// 이게 뭐게 가비 추천: 서버 응답 → 화면 모양(안내 문구·알약·그림판에 채울 선)을 바꾸는 함수와 서버 호출을 가짜 서버로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { drawRecLabel, drawRecView, strokesFromRec } from "../src/features/playground/adapt.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

// 서버 주소는 불러올 때 읽으므로 환경 변수를 정한 뒤에 가져온다
const { getDrawRecs } = await import("../src/features/playground/api.js");

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const ITEM = { id: "d1", source: "common", word: "케이크", alt_answers: ["케익"], strokes: [[[0, 0], [255, 255]]] };

test("그림판에 채울 선: 짧은 변에서 여백 12 를 빼 정사각형으로 맞추고 가로는 가운데 정렬", () => {
  assert.deepEqual(strokesFromRec({ strokes: [[[0, 0], [255, 255]]] }, 360, 280, "#000"), [
    { color: "#000", pts: [{ x: 52, y: 12 }, { x: 308, y: 268 }] },
  ]);
});

test("그림판에 채울 선: 정사각형 칸이면 양쪽 여백이 같고 소수는 반올림한 정수", () => {
  const [stroke] = strokesFromRec({ strokes: [[[0, 0], [128, 128], [255, 255]]] }, 280, 280, "#111");
  assert.deepEqual(stroke.pts, [{ x: 12, y: 12 }, { x: 141, y: 141 }, { x: 268, y: 268 }]);
  assert.ok(stroke.pts.every((p) => Number.isInteger(p.x) && Number.isInteger(p.y)));
});

test("그림판에 채울 선: 선마다 색이 같고 선 개수가 그대로", () => {
  const out = strokesFromRec({ strokes: [[[0, 0], [1, 1]], [[2, 2], [3, 3]], [[4, 4], [5, 5]]] }, 300, 300, "#222");
  assert.equal(out.length, 3);
  assert.ok(out.every((s) => s.color === "#222"));
});

test("추천 보기: 그림이 있으면 그대로", () => {
  assert.deepEqual(drawRecView({ state: "ok", items: [ITEM] }), { items: [ITEM] });
});

test("추천 보기: 다시 해 볼 수 있는 상태는 새로고침이 있고 아니면 없다", () => {
  for (const state of ["preparing", "cooldown", "failed"]) {
    const view = drawRecView({ state, items: [] });
    assert.equal(view.refresh, true, state);
    assert.ok(view.notice.length > 0, state);
  }
  for (const state of ["used_up", "ai_off"]) {
    const view = drawRecView({ state, items: [] });
    assert.equal(view.refresh, false, state);
    assert.ok(view.notice.length > 0, state);
  }
});

test("추천 보기: 응답이 없거나 모르는 상태, 비어 있는 ok 는 안내로", () => {
  assert.equal(drawRecView(null).refresh, true); // 아직·네트워크 오류는 "준비하기 어려워요"로 보고 다시 해 볼 수 있다
  assert.equal(drawRecView({ state: "weird", items: [] }).refresh, true);
  assert.equal(drawRecView({ state: "ok", items: [] }).refresh, false); // 낸 단어를 숨겨 비게 된 경우: 오늘은 여기까지
});

test("카드 알약 글자", () => {
  assert.equal(drawRecLabel({ source: "schedule" }), "일정에서");
  assert.equal(drawRecLabel({ source: "chat" }), "소통방에서");
  assert.equal(drawRecLabel({ source: "common" }), "흔한 단어");
});

test("getDrawRecs 는 GET /play/draw/recommendations 를 부른다", async () => {
  let called = null;
  globalThis.fetch = async (url, init) => {
    called = { url: String(url), method: init?.method ?? "GET" };
    return new Response(JSON.stringify({ state: "ok", items: [ITEM] }), { status: 200, headers: { "content-type": "application/json" } });
  };
  const out = await getDrawRecs();
  assert.equal(called.url, "http://api.test/play/draw/recommendations");
  assert.equal(called.method, "GET");
  assert.deepEqual(out, { state: "ok", items: [ITEM] });
});
