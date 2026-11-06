import assert from "node:assert/strict";
import { test } from "node:test";

import { CATEGORY_LABEL, CHIPS, filterNotices, noticeDate, noticesErrorMessage, preview, unreadCount } from "../src/features/notices/notices.js";

const rows = [
  { id: "a", category: "update", title: "1.2", body: "x" },
  { id: "b", category: "maintenance", title: "점검", body: "y" },
  { id: "c", category: "info", title: "안내", body: "z" },
];

test("칩은 전체 + 서버의 세 종류와 같다", () => {
  assert.deepEqual(CHIPS.map((c) => c.key), ["all", ...Object.keys(CATEGORY_LABEL)]);
});

test("칩으로 거르기: 전체·종류별·모르는 칩은 전체", () => {
  assert.equal(filterNotices(rows, "all").length, 3);
  assert.deepEqual(filterNotices(rows, "maintenance").map((n) => n.id), ["b"]);
  assert.equal(filterNotices(rows, "event").length, 3);
  assert.deepEqual(filterNotices(null, "all"), []);
});

test("안 읽은 수는 폰에 기억한 id 를 뺀다", () => {
  assert.equal(unreadCount(rows, new Set()), 3);
  assert.equal(unreadCount(rows, new Set(["a", "zzz"])), 2);
  assert.equal(unreadCount(null, new Set()), 0);
});

test("날짜는 한국 시간 YYYY.MM.DD", () => {
  assert.equal(noticeDate("2026-11-04T16:00:00Z"), "2026.11.05"); // 한국 시간 새벽 1시
  assert.equal(noticeDate("2026-11-04T01:00:00Z"), "2026.11.04");
  assert.equal(noticeDate(""), "");
  assert.equal(noticeDate("nope"), "");
});

test("미리보기는 첫 글줄, 60자까지", () => {
  assert.equal(preview("\n\n안녕하세요\n둘째 줄"), "안녕하세요");
  assert.equal(preview("가".repeat(70)), `${"가".repeat(60)}…`);
  assert.equal(preview(undefined), "");
});

test("오류 문구", () => {
  assert.equal(noticesErrorMessage(null), "");
  assert.match(noticesErrorMessage({ status: 401 }), /로그인/);
  assert.match(noticesErrorMessage({ status: 503 }), /잠시 볼 수 없어요/);
  assert.match(noticesErrorMessage({ status: 500 }), /불러오지 못했어요/);
});
