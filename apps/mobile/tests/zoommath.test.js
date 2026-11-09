// 사진 확대(핀치·드래그·두 번 탭) 계산 규칙을 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  clampPan,
  clampPinchScale,
  clampScale,
  DOUBLE_TAP_SCALE,
  doubleTapScale,
  fittedSize,
  MAX_SCALE,
  maxPan,
  MIN_SCALE,
  PINCH_MIN_SCALE,
  zoomAround,
} from "../src/features/ai-assistant/zoomMath.js";

test("손을 뗀 뒤 배율은 1배~5배 안으로 맞춘다", () => {
  assert.equal(clampScale(0.3), MIN_SCALE);
  assert.equal(clampScale(2.2), 2.2);
  assert.equal(clampScale(9), MAX_SCALE);
  assert.equal(clampScale(NaN), MIN_SCALE);
  assert.equal(clampScale(Infinity), MIN_SCALE);
});

test("오므리는 중에는 1배 아래로 조금 더 줄어든다", () => {
  assert.equal(clampPinchScale(0.9), 0.9);
  assert.equal(clampPinchScale(0.1), PINCH_MIN_SCALE);
  assert.equal(clampPinchScale(9), MAX_SCALE);
  assert.equal(clampPinchScale(NaN), MIN_SCALE);
});

test("사진이 화면에 잘리지 않게 맞춘 크기를 구한다", () => {
  assert.deepEqual(fittedSize(400, 800, 2), { width: 400, height: 200 }); // 가로 사진: 너비에 맞춘다
  assert.deepEqual(fittedSize(400, 800, 0.25), { width: 200, height: 800 }); // 아주 긴 세로 사진: 높이에 맞춘다
  assert.deepEqual(fittedSize(400, 800, 0), { width: 400, height: 800 }); // 비율을 모르면 화면 크기
  assert.deepEqual(fittedSize(0, 0, 2), { width: 0, height: 0 }); // 화면 크기를 아직 모를 때
});

test("사진이 화면보다 커진 만큼만 옮길 수 있다", () => {
  assert.equal(maxPan(400, 400, 1), 0);
  assert.equal(maxPan(400, 400, 2), 200);
  assert.equal(maxPan(400, 400, 0.8), 0); // 줄어든 배율에서도 음수가 되지 않는다
});

test("가로 사진은 세로로 화면을 넘을 때까지 위아래로 움직이지 않고, 좌우로는 바로 움직인다", () => {
  const { width, height } = fittedSize(400, 800, 2); // 400x200 으로 보인다
  assert.equal(maxPan(width, 400, 3), 400); // 1200 이 되어 좌우로 400 씩
  assert.equal(maxPan(height, 800, 3), 0); // 600 이라 아직 화면 안: 위아래 고정
  assert.equal(maxPan(height, 800, 5), 100); // 1000 이 되어 위아래로 100 씩
});

test("이동 값은 사진 가장자리가 화면 안으로 들어오지 않게 맞춘다", () => {
  assert.equal(clampPan(300, 400, 400, 2), 200);
  assert.equal(clampPan(-300, 400, 400, 2), -200);
  assert.equal(clampPan(120, 400, 400, 2), 120);
  assert.equal(clampPan(50, 400, 400, 1), 0); // 확대 전에는 움직이지 않는다
  assert.equal(clampPan(-0, 400, 400, 1), 0);
  assert.equal(clampPan(NaN, 400, 400, 2), 0);
});

test("손가락 사이 지점이 확대 전후로 같은 자리에 머문다", () => {
  const screenAt = (pan, scale, local) => pan + scale * local;
  // 이동 30, 배율 1.5 에서 화면 100 지점에 있던 사진 위치
  const local = (100 - 30) / 1.5;
  const next = zoomAround(30, 100, 1.5, 3);
  assert.ok(Math.abs(screenAt(next, 3, local) - 100) < 1e-9);
  assert.equal(zoomAround(0, 0, 1, 2), 0); // 화면 가운데에서 벌리면 이동이 없다
  assert.equal(zoomAround(30, 100, 2, 2), 30); // 배율이 그대로면 이동도 그대로
});

test("핀치를 조금씩 나눠 해도 한 번에 한 것과 결과가 같다", () => {
  let pan = 0;
  let scale = 1;
  for (const next of [1.2, 1.5, 2, 3]) {
    pan = zoomAround(pan, 80, scale, next);
    scale = next;
  }
  assert.ok(Math.abs(pan - zoomAround(0, 80, 1, 3)) < 1e-9);
});

test("손가락 지점을 아직 모르면 이동 값을 바꾸지 않는다", () => {
  assert.equal(zoomAround(30, NaN, 1, 2), 30);
  assert.equal(zoomAround(30, 100, 0, 2), 30);
});

test("두 번 누르기: 원래 크기면 2.5배로, 확대돼 있으면 원래 크기로", () => {
  assert.equal(doubleTapScale(1), DOUBLE_TAP_SCALE);
  assert.equal(doubleTapScale(1.02), DOUBLE_TAP_SCALE); // 거의 원래 크기도 확대로
  assert.equal(doubleTapScale(2.5), MIN_SCALE);
  assert.equal(doubleTapScale(5), MIN_SCALE);
});
