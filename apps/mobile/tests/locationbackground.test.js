import assert from "node:assert/strict";
import test from "node:test";

import { pickToSend, toPoint, wantsBackground } from "../src/features/location/background.js";

const base = { enabled: true, consent: true, background: true, paused: false };

test("wantsBackground: 서버 스위치·위치 동의·백그라운드 동의가 모두 있고 일시정지가 아닐 때만 수집한다", () => {
  assert.equal(wantsBackground(base), true);
  assert.equal(wantsBackground({ ...base, enabled: false }), false);
  assert.equal(wantsBackground({ ...base, consent: false }), false);
  assert.equal(wantsBackground({ ...base, background: false }), false);
  assert.equal(wantsBackground({ ...base, paused: true }), false);
  assert.equal(wantsBackground(null), false);
  assert.equal(wantsBackground(undefined), false);
});

test("toPoint: 위도·경도·시각을 서버 모양으로 바꾸고 알 수 없는 정확도는 비운다", () => {
  const loc = { coords: { latitude: 37.5, longitude: 127.1, accuracy: 12.5 }, timestamp: Date.parse("2026-11-06T03:00:00Z") };
  assert.deepEqual(toPoint(loc), { lat: 37.5, lng: 127.1, accuracy_m: 12.5, recorded_at: "2026-11-06T03:00:00.000Z" });
  assert.equal(toPoint({ ...loc, coords: { ...loc.coords, accuracy: -1 } }).accuracy_m, null);
  assert.equal(toPoint({ ...loc, coords: { latitude: 1, longitude: 2 } }).accuracy_m, null);
});

test("pickToSend: 한 번에 많이 쌓여도 가장 최근 몇 개만 보낸다", () => {
  assert.deepEqual(pickToSend([1, 2, 3]), [1, 2, 3]);
  assert.deepEqual(pickToSend([1, 2, 3, 4, 5, 6, 7], 5), [3, 4, 5, 6, 7]);
  assert.deepEqual(pickToSend([], 5), []);
});
