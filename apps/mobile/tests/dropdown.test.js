// 공통 드롭다운: 값·옵션·onChange 만 받는 얇은 Modal 목록인지 소스 구성으로 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const src = readFileSync(new URL("../src/shared/components/Dropdown.js", import.meta.url), "utf8");

test("Dropdown uses a transparent Modal that closes on backdrop touch and Android back", () => {
  assert.match(src, /<Modal\b/);
  assert.match(src, /onRequestClose=/);
  assert.match(src, /transparent/);
  assert.match(src, /ScrollView|FlatList/);
});

test("Dropdown highlights the current value, has a 44 high touch area and accessibility labels", () => {
  assert.match(src, /minHeight: 44/);
  assert.match(src, /accessibilityRole/);
  assert.match(src, /accessibilityState=\{\{ selected/);
  assert.match(src, /accessibilityLabel/);
  assert.match(src, /from "@\/theme"/);
});
