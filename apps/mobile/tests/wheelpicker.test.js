// 휠 선택(WheelPicker): 스크롤 오프셋↔값 변환(순수 함수)과 컴포넌트 구성(소스 검사)을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { indexToOffset, offsetToIndex } from "../src/shared/wheel.js";

const src = readFileSync(new URL("../src/shared/components/WheelPicker.js", import.meta.url), "utf8");

test("offsetToIndex rounds to the nearest row and clamps to the list", () => {
  assert.equal(offsetToIndex(0, 44, 24), 0);
  assert.equal(offsetToIndex(43, 44, 24), 1);
  assert.equal(offsetToIndex(21, 44, 24), 0);
  assert.equal(offsetToIndex(22, 44, 24), 1);
  assert.equal(offsetToIndex(44 * 23, 44, 24), 23);
  assert.equal(offsetToIndex(-50, 44, 24), 0);
  assert.equal(offsetToIndex(99999, 44, 24), 23);
  assert.equal(offsetToIndex(Number.NaN, 44, 24), 0);
  assert.equal(offsetToIndex(10, 44, 0), 0);
});

test("indexToOffset is index times row height", () => {
  assert.equal(indexToOffset(0, 44), 0);
  assert.equal(indexToOffset(7, 44), 308);
  assert.equal(offsetToIndex(indexToOffset(59, 44), 44, 60), 59);
});

test("WheelPicker snaps to rows, three rows of 44, nested scroll for Android", () => {
  assert.match(src, /snapToInterval=\{ITEM_HEIGHT\}/);
  assert.match(src, /decelerationRate="fast"/);
  assert.match(src, /nestedScrollEnabled/);
  assert.match(src, /ITEM_HEIGHT = 44/);
  assert.match(src, /VISIBLE_ROWS = 3/);
});

test("WheelPicker settles the value at the end of scrolling, also on web (debounce)", () => {
  assert.match(src, /onMomentumScrollEnd=/);
  assert.match(src, /onScrollEndDrag=/);
  assert.match(src, /onScroll=/);
  assert.match(src, /setTimeout\(/);
  assert.match(src, /clearTimeout\(/);
  assert.match(src, /offsetToIndex\(/);
  assert.match(src, /scrollTo\(/);
});

test("WheelPicker has typed input: TextInput, number pad, two digits, select all, commit on blur/submit", () => {
  assert.match(src, /<TextInput\b/);
  assert.match(src, /keyboardType="number-pad"/);
  assert.match(src, /maxLength=\{2\}/);
  assert.match(src, /selectTextOnFocus/);
  assert.match(src, /onBlur=/);
  assert.match(src, /onSubmitEditing=/);
  assert.match(src, /parseInput\(/);
});

test("WheelPicker accessibility: adjustable with increment/decrement and label + current value", () => {
  assert.match(src, /accessibilityRole="adjustable"/);
  assert.match(src, /accessibilityActions=/);
  assert.match(src, /increment/);
  assert.match(src, /decrement/);
  assert.match(src, /onAccessibilityAction=/);
  assert.match(src, /accessibilityLabel=\{`\$\{label\} \$\{/);
});

test("WheelPicker uses only theme tokens (no hex colors)", () => {
  assert.match(src, /from "@\/theme"/);
  assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b/);
});
