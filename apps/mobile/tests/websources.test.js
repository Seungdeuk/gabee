// AI 채팅 웹 출처: 사이트 이름 뽑기와 열어도 되는 주소 판별
import assert from "node:assert/strict";
import { test } from "node:test";

import { canOpenWebSource, webSourceHost } from "../src/features/ai-assistant/webSources.js";

test("주소에서 사이트 이름을 뽑고 www 를 뺀다", () => {
  assert.equal(webSourceHost("https://www.kma.go.kr/weather?x=1"), "kma.go.kr");
  assert.equal(webSourceHost("http://news.example.com/a#b"), "news.example.com");
});

test("http·https 가 아닌 주소는 열지 않는다", () => {
  assert.equal(canOpenWebSource("https://example.com"), true);
  assert.equal(canOpenWebSource("javascript:alert(1)"), false);
  assert.equal(canOpenWebSource("gabee://login"), false);
  assert.equal(canOpenWebSource(""), false);
  assert.equal(canOpenWebSource(undefined), false);
});
