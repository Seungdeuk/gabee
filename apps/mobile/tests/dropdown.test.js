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

test("Dropdown: 칸 옆에 화살표를 두지 않는다(시·분 숫자만 보인다)", () => {
  assert.doesNotMatch(src, /▾|caret|chevron/);
});

test("Dropdown: 칸 배경은 흰색 토큰(colors.card)이다", () => {
  assert.match(src, /box: \{[\s\S]*?backgroundColor: colors\.card,[\s\S]*?\}/);
  assert.doesNotMatch(src.match(/box: \{[\s\S]*?\},\n  boxText/)?.[0] ?? "", /colors\.surface\b/);
});

test("Dropdown: 한 줄에 여섯 칸이 들어가도록 칸 가로 여백이 좁고(spacing.xs) 최소 가로 폭을 강제하지 않는다", () => {
  const box = src.match(/box: \{[\s\S]*?\},\n  boxText/)?.[0] ?? "";
  assert.match(box, /paddingHorizontal: spacing\.xs/);
  assert.doesNotMatch(box, /minWidth/);
  assert.match(box, /minHeight: 44/);
});
