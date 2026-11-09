// 확인 필요 기록에서 "어느 부분을 고쳐야 하는지" 안내를 만드는 규칙을 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { reviewGuide, unreadableParts } from "../src/features/ai-assistant/reviewGuide.js";

const body = (...lines) => ["# 제목", "분류: 영수증", ...lines].join("\n");
const record = (extra = {}) => ({ title: "마트 영수증", kind_label: "", body_md: body("- 날짜: 2026-10-15", "우유 2,000원"), has_unread_parts: false, ...extra });
const fields = (r) => reviewGuide(r).map((g) => g.field);

test("제목에 못 읽은 글자가 있으면 제목 안내를 준다", () => {
  assert.deepEqual(reviewGuide(record({ title: "[판독불가] 영수증" })), [
    { field: "제목", text: "제목에 못 읽은 글자가 있어요. 원본을 보고 제목을 고쳐 주세요." },
  ]);
  assert.deepEqual(fields(record({ title: "마트 [?]" })), ["제목"]);
});

test("[판독불가] 줄 수를 센다", () => {
  const g = reviewGuide(record({ body_md: body("a [판독불가]", "b", "[판독불가] c") }));
  assert.deepEqual(g, [{ field: "내용", text: "내용에 못 읽은 글자가 2곳 있어요. 원본을 보고 [판독불가] 자리에 맞는 글자로 고쳐 주세요." }]);
});

test("[불확실]로 끝나는 줄 수를 센다", () => {
  const g = reviewGuide(record({ body_md: body("우유 [불확실]", "빵", "계란 [불확실]") }));
  assert.deepEqual(g, [{ field: "내용", text: "내용에 글자가 흐려 자신 없는 줄이 2개 있어요. 원본과 비교해 틀린 곳을 고쳐 주세요." }]);
});

test("[판독불가]와 [불확실]이 함께 있는 줄은 한 번만 센다", () => {
  const g = reviewGuide(record({ body_md: body("우유 [판독불가] [불확실]") }));
  assert.equal(g.length, 1);
  assert.match(g[0].text, /못 읽은 글자가 1곳/);
});

test("일부를 읽지 못한 경우: has_unread_parts 이거나 본문에 표시가 있을 때", () => {
  const text = "일부를 읽지 못했어요. 원본을 보고 빠진 내용을 적어 주세요.";
  assert.deepEqual(reviewGuide(record({ has_unread_parts: true })), [{ field: "내용", text }]);
  assert.deepEqual(reviewGuide(record({ body_md: body("[읽지 못한 부분]") })), [{ field: "내용", text }]);
});

test("맨 앞 제목 줄의 [판독불가]는 내용으로 세지 않는다", () => {
  const r = record({ title: "[판독불가]", body_md: ["# [판독불가]", "분류: 영수증", "우유"].join("\n") });
  assert.deepEqual(fields(r), ["제목"]);
});

test("여러 이유가 겹치면 제목, 못 읽은 글자, 자신 없는 줄, 일부 순서로 나온다", () => {
  const r = record({ title: "[?]", has_unread_parts: true, kind_label: "영수증", body_md: body("a [불확실]", "b [판독불가]") });
  assert.deepEqual(fields(r), ["제목", "내용", "내용", "내용"]);
  assert.match(reviewGuide(r)[1].text, /못 읽은 글자/);
  assert.match(reviewGuide(r)[2].text, /자신 없는 줄/);
  assert.match(reviewGuide(r)[3].text, /일부를 읽지/);
});

test("종류 안내는 다른 이유가 없을 때만, 받침에 맞는 조사로 나온다", () => {
  assert.equal(reviewGuide(record({ kind_label: "영수증" }))[0].text, "종류가 확실하지 않아요. '영수증'이 맞는지 보고, 틀리면 종류를 바꿔 주세요.");
  assert.equal(reviewGuide(record({ kind_label: "고지서" }))[0].text, "종류가 확실하지 않아요. '고지서'가 맞는지 보고, 틀리면 종류를 바꿔 주세요.");
  assert.deepEqual(fields(record({ kind_label: "영수증", has_unread_parts: true })), ["내용"]);
  assert.equal(reviewGuide(record({ kind_label: "영수증" }))[0].field, "종류");
});

test("아무 이유도 종류도 없거나 기록이 비어 있으면 빈 목록이다", () => {
  assert.deepEqual(reviewGuide(record()), []);
  assert.deepEqual(reviewGuide(null), []);
  assert.deepEqual(reviewGuide(undefined), []);
  assert.deepEqual(reviewGuide({}), []);
  assert.deepEqual(reviewGuide({ title: 5, body_md: null, kind_label: "  " }), []);
});

test("줄을 일반 글과 못 읽은 자리로 나눈다", () => {
  assert.deepEqual(unreadableParts("합계 [판독불가]원"), [
    { text: "합계 ", unreadable: false },
    { text: "못 읽음", unreadable: true },
    { text: "원", unreadable: false },
  ]);
  assert.deepEqual(unreadableParts("[판독불가]"), [{ text: "못 읽음", unreadable: true }]);
  assert.deepEqual(unreadableParts("합계 12,500원"), [{ text: "합계 12,500원", unreadable: false }]);
  assert.deepEqual(unreadableParts(undefined), []);
});
