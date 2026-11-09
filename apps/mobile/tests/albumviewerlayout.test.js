// 앨범 전체 화면 보기: 넘기며 보는 사진 칸이 비지 않게 하는 구성(안드로이드에서 화면 밖 칸을 지우지 않고, 칸 높이를 목록 높이로 정한다): npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const src = readFileSync(new URL("../src/features/family-chat/components/AlbumViewer.js", import.meta.url), "utf8");

test("앨범 뷰어: 넘긴 칸이 비지 않게 화면 밖 칸을 지우는 기능을 끈다", () => {
  // 안드로이드의 FlatList 는 기본으로 화면 밖 칸을 떼어 내고, 다시 넘기면 사진이 그려지지 않을 수 있다
  assert.match(src, /<FlatList[\s\S]*removeClippedSubviews=\{false\}/);
});

test("앨범 뷰어: 사진 칸 높이를 목록이 잰 높이로 정해 웹에서도 높이가 0 으로 접히지 않는다", () => {
  assert.match(src, /useState\(0\)/); // 잰 높이
  assert.match(src, /onLayout=\{\(e\) => setListHeight\(e\.nativeEvent\.layout\.height\)\}/);
  assert.match(src, /style=\{\{ width, height: listHeight > 0 \? listHeight : undefined \}\}/); // 칸마다 가로는 화면 너비, 세로는 목록 높이
  assert.match(src, /list: \{ flex: 1 \}/); // 목록은 위·아래 줄 사이의 남는 높이를 모두 쓴다
});

test("앨범 뷰어: 웹에서도 넘긴 사진 번호가 바뀌게 스크롤 중에도 번호를 갱신한다", () => {
  // react-native-web 은 onMomentumScrollEnd 를 내보내지 않아 "1 / N" 이 그대로이고 저장·메뉴가 첫 사진에 적용됐다
  assert.match(src, /onScroll=\{onScrollEnd\}/);
  assert.match(src, /scrollEventThrottle=\{/);
  assert.match(src, /onMomentumScrollEnd=\{onScrollEnd\}/); // 네이티브는 그대로
  assert.match(src, /prev\.index === index \? prev :/); // 같은 번호면 다시 그리지 않는다
});

test("앨범 뷰어: 잰 높이가 0 인 첫 프레임에는 높이를 지정하지 않는다(예전처럼 목록에 맞춰 늘어난다)", () => {
  assert.match(src, /height: listHeight > 0 \? listHeight : undefined/);
});
