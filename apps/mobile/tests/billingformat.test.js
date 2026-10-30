// 가계 금액 입력(천 단위 쉼표)과 지출 내역 더보기 계산 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { formatMoneyInput, PAGE_SIZE, parseWon, remaining, stripMoney, won } from "../src/features/billing/format.js";

test("금액 입력은 세 자리마다 쉼표를 넣는다", () => {
  assert.equal(formatMoneyInput("1"), "1");
  assert.equal(formatMoneyInput("123"), "123");
  assert.equal(formatMoneyInput("1234"), "1,234");
  assert.equal(formatMoneyInput("1234567"), "1,234,567");
  assert.equal(formatMoneyInput("1000000000"), "1,000,000,000");
});

test("이미 쉼표가 있거나 숫자가 아닌 글자가 섞여도 숫자만 남겨 다시 만든다", () => {
  assert.equal(formatMoneyInput("1,234"), "1,234");
  assert.equal(formatMoneyInput("12,3456"), "123,456");
  assert.equal(formatMoneyInput("1a2b3c4"), "1,234");
  assert.equal(formatMoneyInput("12 345원"), "12,345");
  assert.equal(formatMoneyInput("-5000"), "5,000"); // 음수 기호는 입력으로 받지 않는다
});

test("비어 있거나 숫자가 없으면 빈 글자, 앞의 0은 뺀다", () => {
  assert.equal(formatMoneyInput(""), "");
  assert.equal(formatMoneyInput(null), "");
  assert.equal(formatMoneyInput(undefined), "");
  assert.equal(formatMoneyInput("abc"), "");
  assert.equal(formatMoneyInput("0"), "0");
  assert.equal(formatMoneyInput("007"), "7");
  assert.equal(formatMoneyInput("0001234"), "1,234");
});

test("숫자(서버 값)도 쉼표 글자로 바꾼다", () => {
  assert.equal(formatMoneyInput(55000), "55,000");
  assert.equal(formatMoneyInput(0), "0");
});

test("parseWon 은 쉼표가 있어도 정수로 읽고, 숫자가 아니면 NaN", () => {
  assert.equal(parseWon("1,234,567"), 1234567);
  assert.equal(parseWon(" 12,000 "), 12000);
  assert.equal(parseWon("5000"), 5000);
  assert.equal(parseWon("0"), 0);
  assert.ok(Number.isNaN(parseWon("")));
  assert.ok(Number.isNaN(parseWon("12.5")));
  assert.ok(Number.isNaN(parseWon("abc")));
  assert.ok(Number.isNaN(parseWon("-5,000")));
});

test("입력칸 글자를 parseWon 으로 되읽으면 처음 숫자와 같다", () => {
  for (const n of [1, 999, 1000, 12345, 1234567, 100000000]) {
    assert.equal(parseWon(formatMoneyInput(n)), n);
  }
});

test("stripMoney 는 쉼표와 공백만 뺀다", () => {
  assert.equal(stripMoney("1,234 567"), "1234567");
  assert.equal(stripMoney(""), "");
  assert.equal(stripMoney(null), "");
});

test("won 표시는 그대로 쉼표가 들어간다(바뀌지 않음)", () => {
  assert.equal(won(54300), "54,300원");
});

test("내역은 5개씩 보이고 남은 개수를 센다", () => {
  assert.equal(PAGE_SIZE, 5);
  assert.equal(remaining(12, 5), 7);
  assert.equal(remaining(12, 10), 2);
  assert.equal(remaining(12, 15), 0); // 다 보여 준 뒤에는 0
  assert.equal(remaining(0, 5), 0);
  assert.equal(remaining(5, 5), 0);
});
