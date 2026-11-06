import assert from "node:assert/strict";
import test from "node:test";

import { clampZoom, metersPerPixel, project, tileUrl, tilesFor, worldPx } from "../src/features/location/mapMath.js";

const SEOUL = { lat: 37.5665, lng: 126.978 };
const size = { width: 360, height: 240 };

test("worldPx: 적도·본초자오선은 월드 한가운데", () => {
  const p = worldPx(0, 0, 1);
  assert.ok(Math.abs(p.x - 256) < 1e-6 && Math.abs(p.y - 256) < 1e-6);
});

test("project: 중심 점은 화면 한가운데, 북쪽은 위·동쪽은 오른쪽", () => {
  const mid = project(SEOUL, SEOUL, 16, size);
  assert.ok(Math.abs(mid.x - 180) < 1e-6 && Math.abs(mid.y - 120) < 1e-6);
  const north = project({ lat: SEOUL.lat + 0.001, lng: SEOUL.lng }, SEOUL, 16, size);
  assert.ok(north.y < mid.y && Math.abs(north.x - mid.x) < 1e-6);
  const east = project({ lat: SEOUL.lat, lng: SEOUL.lng + 0.001 }, SEOUL, 16, size);
  assert.ok(east.x > mid.x);
});

test("metersPerPixel: 줌이 1 커지면 절반, 적도에서 줌 0 은 약 156km", () => {
  assert.ok(Math.abs(metersPerPixel(0, 0) - 156543.03392) < 1e-3);
  assert.ok(Math.abs(metersPerPixel(37, 16) * 2 - metersPerPixel(37, 15)) < 1e-6);
});

test("tilesFor: 화면을 빈틈없이 덮고 중심 타일이 포함된다", () => {
  const tiles = tilesFor(SEOUL, 16, size);
  assert.ok(tiles.length >= 4 && tiles.length <= 9);
  const left = Math.min(...tiles.map((t) => t.left));
  const top = Math.min(...tiles.map((t) => t.top));
  const right = Math.max(...tiles.map((t) => t.left + 256));
  const bottom = Math.max(...tiles.map((t) => t.top + 256));
  assert.ok(left <= 0 && top <= 0 && right >= size.width && bottom >= size.height);
  const center = worldPx(SEOUL.lat, SEOUL.lng, 16);
  assert.ok(tiles.some((t) => t.x === Math.floor(center.x / 256) && t.y === Math.floor(center.y / 256)));
});

test("tilesFor: 날짜변경선을 넘어도 타일 번호는 0~2^z-1, 북극 밖 타일은 뺀다", () => {
  const edge = tilesFor({ lat: 0, lng: 179.9999 }, 3, size);
  assert.ok(edge.every((t) => t.x >= 0 && t.x < 8));
  const pole = tilesFor({ lat: 85, lng: 0 }, 3, size);
  assert.ok(pole.every((t) => t.y >= 0 && t.y < 8));
});

test("tileUrl / clampZoom", () => {
  assert.equal(tileUrl({ z: 16, x: 55866, y: 25374 }), "https://tile.openstreetmap.org/16/55866/25374.png");
  assert.equal(clampZoom(30), 18);
  assert.equal(clampZoom(0), 3);
  assert.equal(clampZoom(15.6), 16);
});
