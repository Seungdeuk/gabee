// 데일리 체크 메모·날짜 이동·거르기 순수 함수(커밋 ②): node --import ./tests/register-alias.mjs --test tests/schedule_daily_memo.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MAX_BACK_DAYS,
  MEMO_MAX,
  appliesOnDate,
  canGoNextDay,
  canGoPrevDay,
  canShiftMonth,
  clipMemo,
  dayCardTitle,
  dayHeaderLabel,
  familyRowsOf,
  isRecordableDay,
  itemsOnDate,
  memoLength,
  memoPreview,
  memoShareText,
  memoSheetSub,
  memoStampText,
  recordDateRange,
  shiftMonthView,
  shortDayLabel,
  stepDay,
  todayItemsOf,
  typedDateOf,
  validateMemo,
} from "../src/features/schedule/daily/logic.js";

// 2026-11-03 은 화요일이다(화면 시안 기준 날짜).
const TODAY = "2026-11-03";

// ── 메모 미리보기 (앞 10자) ──

test("메모 미리보기: 10자까지는 그대로, 넘으면 … 를 붙인다", () => {
  assert.equal(memoPreview("가나다라마바사아자차"), "가나다라마바사아자차"); // 정확히 10자
  assert.equal(memoPreview("가나다라마바사아자차카"), "가나다라마바사아자차…"); // 11자
});

test("메모 미리보기: 시안의 예시 문장은 \"비타민D 한 알 먹…\" 이다", () => {
  assert.equal(memoPreview("비타민D 한 알 먹었고 속이 편했어요"), "비타민D 한 알 먹…");
});

test("메모 미리보기: 앞뒤 공백을 빼고 세며, 없으면 빈 글자", () => {
  assert.equal(memoPreview("   120/80   "), "120/80");
  assert.equal(memoPreview(""), "");
  assert.equal(memoPreview(undefined), "");
});

test("메모 미리보기: 이모지처럼 두 글자 이상인 것도 한 글자로 센다", () => {
  assert.equal(memoPreview("😀".repeat(11)), `${"😀".repeat(10)}…`);
});

// ── 메모 글자 수 상한 (MEMO_MAX = 50) ──

test("메모 상한은 50자", () => {
  assert.equal(MEMO_MAX, 50);
});

test("메모 검사: 50자는 통과, 51자는 막는다", () => {
  assert.deepEqual(validateMemo("가".repeat(50)), { ok: true, error: "" });
  assert.deepEqual(validateMemo("가".repeat(51)), { ok: false, error: "메모는 50자까지 쓸 수 있어요" });
});

test("메모 검사: 빈 글자와 공백만 있는 글자는 막는다", () => {
  assert.equal(validateMemo("").ok, false);
  assert.equal(validateMemo("   ").ok, false);
  assert.equal(validateMemo(undefined).ok, false);
});

test("메모 검사: 앞뒤 공백은 글자 수에서 뺀다", () => {
  assert.equal(validateMemo(`  ${"가".repeat(50)}  `).ok, true);
});

test("입력 자르기: 50자를 넘으면 앞 50자만 남긴다(이모지도 한 글자)", () => {
  assert.equal(clipMemo("가".repeat(60)).length, 50);
  assert.equal(memoLength(clipMemo("😀".repeat(60))), 50);
  assert.equal(clipMemo("짧은 메모"), "짧은 메모");
});

// ── 거르기: 요일 규칙 (applies 가 있으면 그것을 쓴다) ──

test("appliesOnDate: applies 가 있으면 요일과 상관없이 그 값을 쓴다", () => {
  assert.equal(appliesOnDate({ days: ["mon"], applies: true }, TODAY), true);
  assert.equal(appliesOnDate({ days: ["tue"], applies: false }, TODAY), false);
});

test("appliesOnDate: applies 가 없으면 반복 요일과 날짜의 요일로 계산한다", () => {
  const tueOnly = { days: ["tue"] };
  assert.equal(appliesOnDate(tueOnly, TODAY), true); // 화요일
  assert.equal(appliesOnDate(tueOnly, "2026-11-02"), false); // 월요일
  assert.equal(appliesOnDate({ days: [] }, TODAY), false);
});

test("itemsOnDate 와 todayItemsOf 는 날짜의 요일에 맞는 항목만, 순서대로 거른다", () => {
  const items = [
    { id: "a", days: ["tue"] },
    { id: "b", days: ["mon", "wed"] },
    { id: "c", days: ["tue", "sun"], applies: false },
    { id: "d", days: ["mon"], applies: true },
  ];
  // 화요일(오늘): a 는 요일이 맞고, c 는 applies 가 거짓, d 는 applies 가 참이라 나온다
  assert.deepEqual(itemsOnDate(items, TODAY).map((x) => x.id), ["a", "d"]);
  // 월요일: b 는 요일이 맞고, d 는 applies 가 참이라 나온다
  assert.deepEqual(itemsOnDate(items, "2026-11-02").map((x) => x.id), ["b", "d"]);
  assert.deepEqual(todayItemsOf(items, TODAY).map((x) => x.id), ["a", "d"]);
});

test("가족 탭 행도 applies 를 따른다(공개된 것만, 요일에 맞는 것)", () => {
  const items = [
    { id: "p", shareWithFamily: true, days: ["tue"] },
    { id: "q", shareWithFamily: true, days: ["mon"] },
    { id: "r", shareWithFamily: false, days: ["tue"] },
    { id: "s", shareWithFamily: true, days: ["mon"], applies: true },
  ];
  // 화요일: p 는 요일이 맞고 공개, s 는 applies 가 참이라 나온다. r 은 공개가 꺼져 빠진다.
  assert.deepEqual(familyRowsOf(items, TODAY).map((x) => x.id), ["p", "s"]);
  assert.deepEqual(familyRowsOf(items, "2026-11-02").map((x) => x.id), ["q", "s"]);
});

// ── 날짜 범위와 이동 ──

test("기록 날짜는 7일 전까지(8일)다", () => {
  assert.equal(MAX_BACK_DAYS, 7);
  const range = recordDateRange(TODAY);
  assert.equal(range.length, 8);
  assert.equal(range[0], "2026-11-03"); // 오늘이 맨 앞
  assert.equal(range[1], "2026-11-02");
  assert.equal(range[7], "2026-10-27"); // 7일 전
});

test("‹ 는 7일 전에서 막히고, › 는 오늘에서 막힌다", () => {
  assert.equal(canGoPrevDay("2026-10-27", TODAY), false);
  assert.equal(canGoPrevDay("2026-10-28", TODAY), true);
  assert.equal(canGoPrevDay(TODAY, TODAY), true);
  assert.equal(canGoNextDay(TODAY, TODAY), false);
  assert.equal(canGoNextDay("2026-11-02", TODAY), true);
});

test("stepDay: 범위 안에서만 움직이고, 범위 밖이면 그대로 둔다", () => {
  assert.equal(stepDay(TODAY, -1, TODAY), "2026-11-02");
  assert.equal(stepDay("2026-11-02", 1, TODAY), TODAY);
  assert.equal(stepDay(TODAY, 1, TODAY), TODAY); // 미래로는 못 간다
  assert.equal(stepDay("2026-10-27", -1, TODAY), "2026-10-27"); // 8일 전으로 못 간다
  assert.equal(stepDay("2026-10-28", -1, TODAY), "2026-10-27");
});

test("날짜 줄 글자: 오늘 / 어제 · 어제 / 그 밖은 요일까지", () => {
  assert.equal(dayHeaderLabel(TODAY, TODAY), "11월 3일 화요일");
  assert.equal(dayHeaderLabel("2026-11-02", TODAY), "11월 2일 월요일 · 어제");
  assert.equal(dayHeaderLabel("2026-11-01", TODAY), "11월 1일 일요일");
});

test("요약 카드 제목: 오늘 / 어제 / 그 밖은 날짜 나의 체크", () => {
  assert.equal(dayCardTitle(TODAY, TODAY), "오늘 나의 체크");
  assert.equal(dayCardTitle("2026-11-02", TODAY), "어제 나의 체크");
  assert.equal(dayCardTitle("2026-11-01", TODAY), "11월 1일 나의 체크");
});

test("기록 가능한 날짜: 오늘 ~ 7일 전만 true, 미래와 8일 전은 false", () => {
  assert.equal(isRecordableDay(TODAY, TODAY), true);
  assert.equal(isRecordableDay("2026-10-27", TODAY), true);
  assert.equal(isRecordableDay("2026-10-26", TODAY), false);
  assert.equal(isRecordableDay("2026-11-04", TODAY), false); // 미래
});

test("달 이동: 옮길 달에 기록할 수 있는 날이 하나라도 있어야 움직인다", () => {
  // 오늘 11/03, 기록 범위는 10/27 ~ 11/03.
  assert.equal(canShiftMonth("2026-11-01", -1, TODAY), true); // 10월에는 10/27 ~ 10/31 이 있다
  assert.equal(canShiftMonth("2026-10-01", -1, TODAY), false); // 9월에는 없다
  assert.equal(canShiftMonth("2026-11-01", 1, TODAY), false); // 12월은 미래
  assert.equal(canShiftMonth("2026-10-01", 1, TODAY), true); // 11월 1일~3일이 있다
});

test("달 화살표: 보고 있는 달을 1일 키로 옮긴다(연도 넘김 포함)", () => {
  assert.equal(shiftMonthView("2026-11-03", -1), "2026-10-01");
  assert.equal(shiftMonthView("2026-11-03", 1), "2026-12-01");
  assert.equal(shiftMonthView("2026-01-15", -1), "2025-12-01");
});

test("직접 입력 검증: 덜 채우면 말 없음, 없는 날짜와 범위 밖은 안내 글자와 함께 키 없음", () => {
  assert.deepEqual(typedDateOf(["2026", "1", ""], TODAY), { key: null, message: "" });
  assert.deepEqual(typedDateOf(["2026", "02", "30"], TODAY), { key: null, message: "없는 날짜예요" });
  assert.deepEqual(typedDateOf(["2026", "02", "29"], TODAY), { key: null, message: "없는 날짜예요" }); // 2026년은 평년
  assert.deepEqual(typedDateOf(["2026", "10", "26"], TODAY), { key: null, message: "오늘부터 7일 전까지만 기록할 수 있어요" });
  assert.deepEqual(typedDateOf(["2026", "11", "04"], TODAY), { key: null, message: "오늘부터 7일 전까지만 기록할 수 있어요" });
  assert.deepEqual(typedDateOf(["2026", "10", "27"], TODAY), { key: "2026-10-27", message: "" });
  assert.deepEqual(typedDateOf(["2026", "11", "03"], TODAY), { key: "2026-11-03", message: "" });
});

test("짧은 날짜와 쓰기 시트 머리 줄", () => {
  assert.equal(shortDayLabel("2026-11-01"), "11월 1일");
  assert.equal(memoSheetSub(TODAY, TODAY), "오늘 메모를 남겨요");
  assert.equal(memoSheetSub("2026-11-01", TODAY), "11월 1일 메모를 남겨요");
});

// ── 전문 팝업 문구 ──

test("전문 팝업 시각 줄: 완료 시각이 있으면 붙이고, 아니면 날짜만", () => {
  const check = { type: "check", goal: 1 };
  assert.equal(memoStampText(TODAY, check, { done: true, count: 0, doneAt: "08:10" }), "11월 3일 · 오전 8:10 완료");
  assert.equal(memoStampText(TODAY, check, { done: false, count: 0, doneAt: null }), "11월 3일");
  assert.equal(memoStampText(TODAY, check, undefined), "11월 3일");
  const count = { type: "count", goal: 8 };
  assert.equal(memoStampText("2026-11-01", count, { done: false, count: 3, doneAt: null }), "11월 1일");
  assert.equal(memoStampText("2026-11-01", count, { done: true, count: 8, doneAt: "15:00" }), "11월 1일 · 오후 3:00 완료");
});

test("공유 상태 문구: 내 메모는 공유 여부로, 가족 탭 메모는 늘 가족에게 보임", () => {
  assert.equal(memoShareText({ shared: false, mine: true }), "나만 볼 수 있는 메모예요");
  assert.equal(memoShareText({ shared: true, mine: true }), "가족에게 보이는 메모예요");
  assert.equal(memoShareText({ shared: false, mine: false }), "가족에게 보이는 메모예요");
});
