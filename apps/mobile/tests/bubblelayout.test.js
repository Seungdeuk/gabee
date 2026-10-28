// 말풍선 레이아웃 규칙(웹에서 상대 말풍선이 한 글자씩 줄바꿈되던 문제): 스타일 소스를 검사한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const src = readFileSync(new URL("../src/features/family-chat/components/MessageBubble.js", import.meta.url), "utf8");

/**
 * styles 객체에서 한 스타일 줄을 꺼낸다.
 * @param {string} name 스타일 이름
 * @returns {string}
 */
function rule(name) {
  const line = src.split("\n").find((l) => l.trim().startsWith(`${name}: {`));
  assert.ok(line, `${name} 스타일이 있어야 한다`);
  return line;
}

test("상대 말풍선 column 은 row 기준으로 확정되는 maxWidth 를 가진다", () => {
  assert.match(rule("column"), /maxWidth: "\d+%"/);
});

test("상대 말풍선은 내용 폭인 column 의 70% 같은 순환 퍼센트에 기대지 않는다", () => {
  assert.match(rule("otherBubble"), /maxWidth: "100%"/);
});
