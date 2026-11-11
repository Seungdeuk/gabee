import assert from "node:assert/strict";
import { test } from "node:test";

import { PAGE_SIZE, PAGE_WINDOW, clampPage, noticeDate, noticesErrorMessage, pageCount, pageSlice, pageWindow, preview, summaryParts, unreadCount } from "../src/features/notices/notices.js";

const rows = [
  { id: "a", category: "update", title: "1.2", body: "x" },
  { id: "b", category: "maintenance", title: "점검", body: "y" },
  { id: "c", category: "info", title: "안내", body: "z" },
];

const many = (n) => Array.from({ length: n }, (_, i) => ({ id: `n${i}`, category: "info", title: `공지 ${i}`, body: "x" }));

test("페이지는 10개씩이고 10개 이하면 한 쪽(쪽 이동 없음)이다", () => {
  assert.equal(PAGE_SIZE, 10);
  assert.equal(pageCount(0), 1);
  assert.equal(pageCount(10), 1);
  assert.equal(pageCount(11), 2);
  assert.equal(pageCount(100), 10);
  assert.equal(pageCount(null), 1);
});

test("pageSlice: 최근순 그대로 쪽마다 10개씩 자른다(마지막 쪽은 남은 만큼)", () => {
  const rows25 = many(25);
  assert.deepEqual(pageSlice(rows25, 0).map((n) => n.id), rows25.slice(0, 10).map((n) => n.id));
  assert.deepEqual(pageSlice(rows25, 1).map((n) => n.id), rows25.slice(10, 20).map((n) => n.id));
  assert.equal(pageSlice(rows25, 2).length, 5);
  assert.deepEqual(pageSlice(null, 0), []);
  assert.equal(pageSlice(many(3), 0).length, 3);
});

test("pageWindow: 쪽 번호는 5개씩 묶어 보인다(1~5, 6~10, …), 마지막 묶음은 남은 만큼", () => {
  assert.equal(PAGE_WINDOW, 5);
  assert.deepEqual(pageWindow(0, 3), [0, 1, 2]); // 3쪽뿐이면 3개만
  assert.deepEqual(pageWindow(0, 10), [0, 1, 2, 3, 4]); // < 1 | 2 | 3 | 4 | 5 >
  assert.deepEqual(pageWindow(4, 10), [0, 1, 2, 3, 4]); // 5쪽까지는 같은 묶음
  assert.deepEqual(pageWindow(5, 10), [5, 6, 7, 8, 9]); // 6쪽에서 묶음이 넘어간다
  assert.deepEqual(pageWindow(9, 12), [5, 6, 7, 8, 9]);
  assert.deepEqual(pageWindow(10, 12), [10, 11]); // 마지막 묶음
  assert.deepEqual(pageWindow(0, 1), [0]);
});

test("summaryParts: 목록 위 총 N건 문구를 숫자만 따로 꾸밀 수 있게 세 토막으로 준다", () => {
  assert.deepEqual(summaryParts(30), ["총 ", "30", "건의 공지사항이 있어요."]);
  assert.deepEqual(summaryParts(1), ["총 ", "1", "건의 공지사항이 있어요."]);
  assert.deepEqual(summaryParts(null), ["총 ", "0", "건의 공지사항이 있어요."]);
});

test("clampPage: 범위를 벗어난 쪽은 가까운 쪽으로(새로고침으로 목록이 줄어도 빈 쪽이 안 보인다)", () => {
  assert.equal(clampPage(0, 25), 0);
  assert.equal(clampPage(2, 25), 2);
  assert.equal(clampPage(5, 25), 2);
  assert.equal(clampPage(-1, 25), 0);
  assert.equal(clampPage(3, 5), 0);
  assert.equal(clampPage(Number.NaN, 25), 0);
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

test("공지사항 화면: 칩 없이 목록으로 보이고, 10개를 넘으면 쪽 이동이 나온다", async () => {
  const { readFileSync } = await import("node:fs");
  const screen = readFileSync(new URL("../src/features/notices/screens/NoticesScreen.js", import.meta.url), "utf8");
  assert.doesNotMatch(screen, /CHIPS|filterNotices|tablist/); // 종류 칩은 없다
  // 박스 카드가 아니라 구분선으로 나뉜 평면 목록 + 오른쪽 화살표 + 위에 "총 N건"
  assert.doesNotMatch(screen, /card: \{[^}]*borderRadius/);
  assert.match(screen, /row: \{[^}]*borderBottomWidth: 1/);
  assert.match(screen, /name="chevron-forward"/);
  assert.match(screen, /summaryParts\(rows\?\.length\)/);
  assert.match(screen, /pageSlice\(rows, view\)/); // 한 쪽만 그린다(범위를 벗어난 쪽은 clampPage 로 되돌린다)
  assert.match(screen, /clampPage\(page, rows\?\.length\)/);
  assert.match(screen, /pages > 1 \?/); // 쪽이 둘 이상일 때만 이동 줄
  assert.match(screen, /accessibilityLabel="이전 쪽"/);
  assert.match(screen, /accessibilityLabel="다음 쪽"/);
  assert.match(screen, /pageWindow\(view, pages\)/); // 쪽 번호는 한 번에 5개까지
  assert.match(screen, /accessibilityLabel=\{`\$\{n \+ 1\}쪽`\}/); // 번호마다 "n쪽" 이름
});
