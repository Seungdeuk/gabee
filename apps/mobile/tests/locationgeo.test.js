import assert from "node:assert/strict";
import test from "node:test";

import { agoText, projectItems } from "../src/features/location/geo.js";

const box = { width: 300, height: 200, pad: 20 };

test("projectItems: 점이 없으면 빈 배열", () => {
  assert.deepEqual(projectItems([], box), []);
});

test("projectItems: 점이 상자 안에 들어오고 북쪽이 위쪽이다", () => {
  const out = projectItems(
    [
      { id: "a", lat: 37.57, lng: 126.98 },
      { id: "b", lat: 37.58, lng: 126.99 },
    ],
    box,
  );
  for (const p of out) {
    assert.ok(p.x >= 0 && p.x <= box.width && p.y >= 0 && p.y <= box.height);
  }
  assert.ok(out[1].y < out[0].y, "북쪽(b)이 화면 위쪽이어야 한다");
  assert.ok(out[1].x > out[0].x, "동쪽(b)이 화면 오른쪽이어야 한다");
});

test("projectItems: 한 점뿐이면 가운데에 놓이고 활동 구역이 반지름을 가진다", () => {
  const [p] = projectItems(
    [{ id: "a", lat: 37.5, lng: 127, zone: { center_lat: 37.5, center_lng: 127, radius_m: 300 } }],
    box,
  );
  assert.ok(Math.abs(p.x - box.width / 2) < 1 && Math.abs(p.y - box.height / 2) < 1);
  assert.ok(p.zone.r > 0 && p.zone.r <= Math.min(box.width, box.height) / 2);
});

test("agoText: 분·시간·하루 단위", () => {
  const now = Date.parse("2026-11-05T12:00:00Z");
  assert.equal(agoText(null, now), "");
  assert.equal(agoText("2026-11-05T11:59:50Z", now), "방금");
  assert.equal(agoText("2026-11-05T11:30:00Z", now), "30분 전");
  assert.equal(agoText("2026-11-05T09:00:00Z", now), "3시간 전");
  assert.equal(agoText("2026-11-03T09:00:00Z", now), "하루 넘게 전");
});
