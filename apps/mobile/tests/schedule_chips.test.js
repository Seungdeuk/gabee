// 누구 칩 줄(자주 쓰는 사람)·주제 폼의 순수 로직 시험: node --import ./tests/register-alias.mjs --test tests/schedule_chips.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  hiddenMembers,
  hideId,
  pruneHidden,
  restoreHidden,
  serializeHidden,
  showId,
  topicErrorMessage,
  validateTopicName,
  visibleMembers,
} from "../src/features/schedule/favorites.js";

const all = [{ id: "mom" }, { id: "dad" }, { id: "aunt" }];
const ids = (list) => list.map((m) => m.id);

test("칩 줄: 처음엔 모두 보이고, 뺀 사람은 빠진다", () => {
  assert.deepEqual(ids(visibleMembers(all, [], [])), ["mom", "dad", "aunt"]);
  assert.deepEqual(ids(visibleMembers(all, ["dad"], [])), ["mom", "aunt"]);
  assert.deepEqual(ids(hiddenMembers(all, ["dad"], [])), ["dad"]);
});

test("뺀 사람이라도 선택돼 있으면 칩 줄에 남는다(수정 화면)", () => {
  assert.deepEqual(ids(visibleMembers(all, ["dad"], ["dad"])), ["mom", "dad", "aunt"]);
  assert.deepEqual(ids(hiddenMembers(all, ["dad"], ["dad"])), []);
});

test("빼기·다시 넣기", () => {
  assert.deepEqual(hideId([], "mom"), ["mom"]);
  assert.deepEqual(hideId(["mom"], "mom"), ["mom"]);
  assert.deepEqual(showId(["mom", "dad"], "mom"), ["dad"]);
});

test("저장 복원: 모양이 이상하면 빈 목록, 중복·비문자 제거", () => {
  assert.deepEqual(restoreHidden(serializeHidden(["a", "b"])), ["a", "b"]);
  assert.deepEqual(restoreHidden(null), []);
  assert.deepEqual(restoreHidden("{not json"), []);
  assert.deepEqual(restoreHidden('{"a":1}'), []);
  assert.deepEqual(restoreHidden('["a",1,"a",""]'), ["a"]);
});

test("가족에서 사라진 id 는 버린다", () => {
  assert.deepEqual(pruneHidden(["dad", "gone"], all), ["dad"]);
  assert.deepEqual(ids(visibleMembers(all, ["gone"], [])), ["mom", "dad", "aunt"]);
});

test("주제 이름 검사", () => {
  assert.deepEqual(validateTopicName("  운동  "), { ok: true, name: "운동" });
  assert.equal(validateTopicName("   ").ok, false);
  assert.equal(validateTopicName(undefined).ok, false);
  assert.equal(validateTopicName("가".repeat(30)).ok, true);
  assert.equal(validateTopicName("가".repeat(31)).ok, false);
});

test("주제 만들기 실패 메시지", () => {
  assert.equal(topicErrorMessage({ code: "topic_exists" }), "이미 있는 주제예요");
  assert.equal(topicErrorMessage({ code: "invalid_topic" }), "주제 이름을 확인해 주세요");
  assert.equal(topicErrorMessage(new Error("x")), "주제를 만들지 못했어요");
});
