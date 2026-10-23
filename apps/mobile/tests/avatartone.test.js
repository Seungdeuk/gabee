// 아바타 색 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import avatarTone from "../src/shared/avatarTone.js";
import { avatarPalette } from "../src/theme/index.js";

test("같은 입력은 항상 같은 색", () => {
  assert.equal(avatarTone("user-1"), avatarTone("user-1"));
  assert.equal(avatarTone(" 엄마 "), avatarTone("엄마"));
  assert.equal(avatarTone(7), avatarTone("7"));
});

test("고른 색은 늘 팔레트 안", () => {
  for (let i = 0; i < 200; i++) assert.ok(avatarPalette.includes(avatarTone(`u${i}`)));
});

test("다른 입력은 팔레트 전체에 고르게 퍼진다", () => {
  const count = new Map();
  for (let i = 0; i < 600; i++) {
    const t = avatarTone(`user-${i}`);
    count.set(t, (count.get(t) ?? 0) + 1);
  }
  assert.equal(count.size, avatarPalette.length);
  for (const n of count.values()) assert.ok(n > 600 / avatarPalette.length / 2, `치우침: ${n}`);
});

test("빈 키는 첫 칸", () => {
  for (const k of ["", "  ", null, undefined]) assert.equal(avatarTone(k), avatarPalette[0]);
});
