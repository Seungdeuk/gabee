// 데일리 체크 순수 로직 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ALL_DAYS,
  WEEKDAYS,
  COUNT_MAX,
  applyCheck,
  applyStep,
  buildItem,
  countChipText,
  daysLabel,
  dragTargetIndex,
  familyRowsOf,
  formatClock,
  formatDayLabel,
  formatGoal,
  hideTab,
  isDone,
  isScheduledOn,
  itemDescription,
  itemSubText,
  lastRecordOf,
  matchDayPreset,
  moveIndex,
  nowClock,
  normalizeTabs,
  parseGoal,
  placeVisible,
  presetDays,
  progressOf,
  reorderTabs,
  showTab,
  shiftOffset,
  stepGoalText,
  tabLabel,
  todayItemsOf,
  validateItem,
  visibleTabIds,
  weekdayKeyOf,
  CALL_ITEM_KEYWORD,
  CHEER_KINDS,
  CHEER_MESSAGES,
  cheerKindLabel,
  cheerSubtitle,
  dateGroupLabel,
  findCallItem,
  groupCheersByDate,
  onboardingChoices,
  onboardingItem,
  receivedTodayOf,
  shiftDayKey,
  talkingPoints,
} from "../src/features/schedule/daily/logic.js";

const ALL = ALL_DAYS;
const check = (over = {}) => ({ id: "c", name: "약", type: "check", goal: 1, unit: "", days: ALL, alarm: false, shareWithFamily: true, ...over });
const count = (over = {}) => ({ id: "n", name: "물", type: "count", goal: 8, unit: "잔", days: ALL, alarm: false, shareWithFamily: true, ...over });

test("요일: 2026-11-02 는 월요일이고 월요일 기준 키를 쓴다", () => {
  assert.equal(weekdayKeyOf("2026-11-02"), "mon");
  assert.equal(weekdayKeyOf("2026-11-01"), "sun");
  assert.equal(weekdayKeyOf("2026-11-07"), "sat");
  assert.equal(formatDayLabel("2026-11-02"), "11월 2일 월요일");
});

test("반복 요일: 평일만 고른 항목은 토요일에 빠진다", () => {
  const weekdayItem = check({ days: WEEKDAYS });
  assert.equal(isScheduledOn(weekdayItem, "2026-11-02"), true); // 월
  assert.equal(isScheduledOn(weekdayItem, "2026-11-07"), false); // 토
  const list = todayItemsOf([weekdayItem, check({ id: "x", days: ["sat"] })], "2026-11-02");
  assert.deepEqual(list.map((i) => i.id), ["c"]);
});

test("완료 판정: 한 번 체크는 done, 횟수는 목표 도달 여부", () => {
  assert.equal(isDone(check(), undefined), false);
  assert.equal(isDone(check(), { done: true }), true);
  assert.equal(isDone(count(), { count: 7 }), false);
  assert.equal(isDone(count(), { count: 8 }), true);
});

test("한 번 체크 토글: 켜면 시각을 넣고 끄면 지운다", () => {
  const on = applyCheck(undefined, "08:10");
  assert.deepEqual(on, { done: true, count: 0, doneAt: "08:10" });
  assert.deepEqual(applyCheck(on, "09:00"), { done: false, count: 0, doneAt: null });
});

test("횟수 증감: 0과 목표 사이에 머물고, 목표에 닿으면 완료 시각을 남긴다", () => {
  const item = count({ goal: 3 });
  assert.equal(applyStep(item, undefined, -1, "07:00").count, 0);
  const two = applyStep(item, undefined, 2, "07:00");
  assert.equal(two.done, false);
  const three = applyStep(item, two, 1, "07:30");
  assert.deepEqual(three, { done: true, count: 3, doneAt: "07:30" });
  assert.equal(applyStep(item, three, -1, "08:00").doneAt, null); // 목표 아래로 내리면 완료가 풀린다
});

test("횟수는 목표를 넘겨도 계속 올라간다(상한 9999), 완료 시각은 처음 닿은 때 그대로", () => {
  const item = count({ goal: 3 });
  const three = { done: true, count: 3, doneAt: "07:30" };
  const four = applyStep(item, three, 1, "08:00");
  assert.deepEqual(four, { done: true, count: 4, doneAt: "07:30" }); // 4/3 도 완료, 시각은 그대로
  assert.equal(applyStep(item, { count: 9999 }, 5, "09:00").count, 9999); // 상한
  assert.equal(COUNT_MAX, 9999);
});

test("목표를 줄여도 count 는 깎지 않는다: 완료 판정만 새 목표로 다시 본다", () => {
  const lowered = count({ goal: 2 });
  const entry = { count: 5, done: true, doneAt: "07:00" };
  assert.equal(isDone(lowered, entry), true); // 5 >= 2
  assert.equal(entry.count, 5);
  assert.equal(isDone(count({ goal: 8 }), entry), false); // 5 < 8 이면 아직 미완료
});

test("완료 판정: 횟수는 count >= goal (목표와 같아도 완료)", () => {
  assert.equal(isDone(count({ goal: 3 }), { count: 2 }), false);
  assert.equal(isDone(count({ goal: 3 }), { count: 3 }), true);
  assert.equal(isDone(count({ goal: 3 }), { count: 4 }), true);
});

test("진행률: 목표를 넘긴 습관도 한 번만 세고, 완료 수는 전체를 넘지 않는다", () => {
  const items = [count({ id: "w", goal: 8 }), check({ id: "a" })];
  const entries = { w: { count: 10, done: true }, a: { done: true } };
  assert.deepEqual(progressOf(items, (i) => entries[i.id]), { done: 2, total: 2, pct: 100 });
});

test("횟수 칩 글자: 현재/목표, 목표를 넘기면 10/8 처럼 그대로", () => {
  assert.equal(countChipText({ count: 5 }, 8), "5/8");
  assert.equal(countChipText({ count: 10 }, 8), "10/8");
  assert.equal(countChipText(undefined, 8), "0/8");
});

test("진행률: 완료 수와 퍼센트, 항목이 없으면 0", () => {
  const items = [check({ id: "a" }), check({ id: "b" }), count({ id: "c", goal: 2 })];
  const entries = { a: { done: true }, c: { count: 2 } };
  assert.deepEqual(progressOf(items, (i) => entries[i.id]), { done: 2, total: 3, pct: 67 });
  assert.deepEqual(progressOf([], () => undefined), { done: 0, total: 0, pct: 0 });
});

test("가족 탭: 가족에게 보이기가 꺼진 항목과 요일이 안 맞는 항목은 빠진다", () => {
  const rows = familyRowsOf(
    [check({ id: "a" }), check({ id: "b", shareWithFamily: false }), check({ id: "c", days: ["sat"] })],
    "2026-11-02",
  );
  assert.deepEqual(rows.map((r) => r.id), ["a"]);
});

test("마지막 기록: 완료된 것 중 가장 늦은 시각, 없으면 null", () => {
  const rows = [
    { ...check({ id: "a" }), entry: { done: true, doneAt: "10:12" } },
    { ...check({ id: "b" }), entry: { done: true, doneAt: "08:30" } },
    { ...check({ id: "c" }), entry: { done: false, doneAt: null } },
  ];
  assert.equal(lastRecordOf(rows), "10:12");
  assert.equal(lastRecordOf([{ ...check(), entry: undefined }]), null);
});

test("탭 라벨은 '이름 완료/전체'", () => {
  assert.equal(tabLabel("엄마", 3, 3), "엄마 3/3");
  assert.equal(tabLabel("나", 2, 4), "나 2/4");
});

test("탭 순서: 새 가족은 뒤에 붙고, 없어진 가족은 빠지며, 숨김은 보이는 목록에서 뺀다", () => {
  const tabs = normalizeTabs({ order: ["dad", "gone", "mom"], hidden: ["mom", "gone"] }, ["mom", "dad", "son"]);
  assert.deepEqual(tabs, { order: ["dad", "mom", "son"], hidden: ["mom"] });
  assert.deepEqual(visibleTabIds(tabs), ["dad", "son"]);
  assert.deepEqual(normalizeTabs(null, ["mom"]), { order: ["mom"], hidden: [] });
});

test("숨기기·다시 보이기", () => {
  const tabs = { order: ["mom", "dad"], hidden: [] };
  const hidden = hideTab(tabs, "dad");
  assert.deepEqual(hidden.hidden, ["dad"]);
  assert.equal(hideTab(hidden, "dad"), hidden);
  assert.deepEqual(showTab(hidden, "dad").hidden, []);
});

// ── 끌어서 순서 바꾸기 ──

test("줄 옮기기: 범위 밖이거나 같은 자리면 그대로", () => {
  assert.deepEqual(moveIndex(["a", "b", "c"], 0, 2), ["b", "c", "a"]);
  assert.deepEqual(moveIndex(["a", "b", "c"], 2, 0), ["c", "a", "b"]);
  const same = ["a", "b"];
  assert.equal(moveIndex(same, 1, 1), same);
  assert.equal(moveIndex(same, 0, 5), same);
});

test("보이는 자리 채우기: 숨은 줄은 제자리, 보이는 줄끼리만 섞인다", () => {
  assert.deepEqual(placeVisible(["a", "x", "b"], ["a", "b"], ["b", "a"]), ["b", "x", "a"]);
});

test("탭 끌기: 보이는 탭끼리 옮기고 숨긴 탭은 제자리다", () => {
  const tabs = { order: ["mom", "dad", "son"], hidden: ["dad"] };
  // 보이는 것은 mom, son. 첫째(mom)를 둘째 자리(son)로 옮기면 두 칸이 바뀐다
  assert.deepEqual(reorderTabs(tabs, 0, 1).order, ["son", "dad", "mom"]);
  assert.deepEqual(reorderTabs(tabs, 1, 0).order, ["son", "dad", "mom"]);
});

test("끄는 줄의 도착 자리: 손가락 이동을 줄 간격으로 바꿔 범위 안에 가둔다", () => {
  const stride = 82;
  assert.equal(dragTargetIndex(0, 0, stride, 4), 0);
  assert.equal(dragTargetIndex(0, 40, stride, 4), 0); // 절반 조금 넘어도 아직 같은 자리(반올림)
  assert.equal(dragTargetIndex(0, 45, stride, 4), 1);
  assert.equal(dragTargetIndex(1, 170, stride, 4), 3);
  assert.equal(dragTargetIndex(3, 1000, stride, 4), 3); // 범위 밖은 끝에 머문다
  assert.equal(dragTargetIndex(2, -1000, stride, 4), 0);
  assert.equal(dragTargetIndex(0, 50, stride, 0), 0);
});

test("비켜 주기: 끄는 줄이 아래로 가면 사이 줄들이 위로, 위로 가면 아래로 한 칸씩", () => {
  const stride = 82;
  // 0 → 2: 1, 2 가 위로
  assert.equal(shiftOffset(1, 0, 2, stride), -stride);
  assert.equal(shiftOffset(2, 0, 2, stride), -stride);
  assert.equal(shiftOffset(3, 0, 2, stride), 0);
  // 3 → 1: 1, 2 가 아래로
  assert.equal(shiftOffset(1, 3, 1, stride), stride);
  assert.equal(shiftOffset(2, 3, 1, stride), stride);
  assert.equal(shiftOffset(0, 3, 1, stride), 0);
  // 제자리면 아무도 안 움직인다
  assert.equal(shiftOffset(2, 2, 2, stride), 0);
});

// ── 반복 요일 빠른 선택 ──

test("빠른 선택 요일: 평일만=월~금, 주말만=토·일, 모두=7개, 해제=0개", () => {
  assert.deepEqual(presetDays("weekdays"), ["mon", "tue", "wed", "thu", "fri"]);
  assert.deepEqual(presetDays("weekend"), ["sat", "sun"]);
  assert.equal(presetDays("all").length, 7);
  assert.deepEqual(presetDays("none"), []);
});

test("빠른 선택 칩 표시: 지금 고른 요일과 같은 칩만 눌린 상태", () => {
  assert.equal(matchDayPreset(["sun", "sat"]), "weekend");
  assert.equal(matchDayPreset(["fri", "thu", "wed", "tue", "mon"]), "weekdays");
  assert.equal(matchDayPreset(ALL), "all");
  assert.equal(matchDayPreset([]), "none");
  assert.equal(matchDayPreset(["mon", "wed"]), null);
});

test("목표 글자 해석: 숫자 뒤에 단위가 붙는다", () => {
  assert.deepEqual(parseGoal("8잔"), { goal: 8, unit: "잔" });
  assert.deepEqual(parseGoal("30 분"), { goal: 30, unit: "분" });
  assert.deepEqual(parseGoal("10"), { goal: 10, unit: "" });
  assert.equal(parseGoal("잔"), null);
  assert.equal(parseGoal("0잔"), null);
  assert.equal(parseGoal(""), null);
  assert.equal(formatGoal(8, "잔"), "8잔");
});

test("목표 +/−: 단위는 그대로 두고 1 아래로 내려가지 않는다", () => {
  assert.equal(stepGoalText("8잔", 1), "9잔");
  assert.equal(stepGoalText("8잔", -1), "7잔");
  assert.equal(stepGoalText("1잔", -1), "1잔");
  assert.equal(stepGoalText("쪽", 1), "2");
});

test("저장 전 검사: 이름, 요일, 횟수 목표", () => {
  assert.equal(validateItem({ name: "  ", type: "check", days: ALL }).ok, false);
  assert.equal(validateItem({ name: "약", type: "check", days: [] }).ok, false);
  assert.equal(validateItem({ name: "물", type: "count", goalText: "잔", days: ALL }).ok, false);
  assert.equal(validateItem({ name: "물", type: "count", goalText: "8잔", days: ALL }).ok, true);
  // 한 번 체크는 목표 글자가 틀려도 상관없다
  assert.equal(validateItem({ name: "약", type: "check", goalText: "", days: ALL }).ok, true);
});

test("항목 모양 만들기: 요일은 월~일 순서, 한 번 체크는 목표 1·단위 없음", () => {
  const item = buildItem({ name: " 물 마시기 ", type: "count", goalText: "8잔", days: ["sun", "mon"], alarm: true, shareWithFamily: false });
  assert.deepEqual(item, {
    id: undefined,
    name: "물 마시기",
    type: "count",
    goal: 8,
    unit: "잔",
    days: ["mon", "sun"],
    alarm: true,
    shareWithFamily: false,
  });
  const once = buildItem({ name: "약", type: "check", goalText: "", days: WEEKDAYS });
  assert.equal(once.goal, 1);
  assert.equal(once.unit, "");
  assert.equal(once.type, "check");
});

test("반복 요일 글자: 매일 / 평일 / 주말 / 골라 쓴 요일 (만 없이)", () => {
  assert.equal(daysLabel(ALL), "매일");
  assert.equal(daysLabel(WEEKDAYS), "평일");
  assert.equal(daysLabel(["sat", "sun"]), "주말");
  assert.equal(daysLabel(["mon", "wed", "fri"]), "월·수·금");
  assert.equal(itemDescription(check({ days: WEEKDAYS })), "평일");
  assert.equal(itemDescription(check({ days: ["sat", "sun"] })), "주말");
  assert.equal(itemDescription(check({ days: ["mon", "wed", "fri"] })), "월·수·금");
  assert.equal(itemDescription(count({ days: WEEKDAYS })), "평일 · 하루 8잔");
  assert.equal(itemDescription(count({ days: ALL })), "매일 · 하루 8잔");
  assert.equal(itemDescription(count({ days: ["sat", "sun"], goal: 10, unit: "쪽" })), "주말 · 하루 10쪽");
  assert.equal(itemDescription(count({ days: ["mon", "wed", "fri"], goal: 30, unit: "분" })), "월·수·금 · 하루 30분");
});

test("항목 아래 한 줄 글자와 시각 표시", () => {
  assert.equal(formatClock("08:10"), "오전 8:10");
  assert.equal(formatClock("15:05"), "오후 3:05");
  assert.equal(formatClock("12:00"), "오후 12:00");
  assert.equal(formatClock(""), "");
  assert.equal(itemSubText(check(), { done: true, doneAt: "08:10" }), "오전 8:10 완료");
  assert.equal(itemSubText(check(), undefined), "아직이에요");
  assert.equal(itemSubText(check(), undefined, { family: true }), "아직 기록이 없어요");
  assert.equal(itemSubText(count(), { count: 3 }), "하루 8잔 목표");
  assert.match(nowClock(new Date(2026, 10, 2, 7, 5)), /^07:05$/);
});

test("완료 한 줄 글자: 한 번 체크는 시각과 함께, 횟수는 목표 글자(시안 값의 형식)", () => {
  const vit = { id: "v", name: "영양제 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true };
  const water = { id: "w", name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: false, shareWithFamily: true };
  assert.equal(itemSubText(vit, { done: true, count: 0, doneAt: "08:10" }), "오전 8:10 완료");
  assert.equal(itemSubText(vit, { done: true, count: 0, doneAt: "16:30" }), "오후 4:30 완료");
  assert.equal(itemSubText(water, { done: false, count: 5, doneAt: null }), "하루 8잔 목표");
  assert.equal(countChipText({ count: 5 }, 8), "5/8");
  assert.equal(isDone(water, { done: false, count: 5, doneAt: null }), false);
});

// ── 2차: 온보딩 · 응원 · 전화 ──

test("날짜 이동과 묶음 머리글: 오늘·어제·그 밖은 월 일", () => {
  assert.equal(shiftDayKey("2026-11-01", 1), "2026-11-02");
  assert.equal(shiftDayKey("2026-11-02", -3), "2026-10-30");
  assert.equal(dateGroupLabel("2026-11-02", "2026-11-02"), "오늘");
  assert.equal(dateGroupLabel("2026-11-01", "2026-11-02"), "어제");
  assert.equal(dateGroupLabel("2026-10-30", "2026-11-02"), "10월 30일");
});

test("응원 종류와 머리 줄", () => {
  assert.deepEqual(CHEER_KINDS.map((k) => k.label), ["사랑해요", "최고예요", "잘하셨어요"]);
  assert.equal(cheerKindLabel("best"), "최고예요");
  assert.equal(cheerKindLabel("nope"), "");
  assert.equal(CHEER_MESSAGES.length, 2);
  assert.equal(cheerSubtitle(3, 3), "오늘 3/3 모두 챙기셨어요");
  assert.equal(cheerSubtitle(1, 3), "오늘 1/3 챙기셨어요");
});

test("받은 응원: 오늘 받은 것만 세고, 날짜별로 최근 날짜 먼저·같은 날은 늦은 시각 먼저", () => {
  const list = [
    { id: "a", direction: "received", date: "2026-11-02", time: "09:00" },
    { id: "b", direction: "received", date: "2026-11-02", time: "16:02" },
    { id: "c", direction: "received", date: "2026-11-01", time: "20:15" },
    { id: "d", direction: "sent", date: "2026-11-02", time: "10:00" },
  ];
  assert.deepEqual(receivedTodayOf(list, "2026-11-02").map((c) => c.id), ["a", "b"]);
  const groups = groupCheersByDate(list.filter((c) => c.direction === "received"), "2026-11-02");
  assert.deepEqual(groups.map((g) => g.label), ["오늘", "어제"]);
  assert.deepEqual(groups[0].items.map((c) => c.id), ["b", "a"]);
});

test("온보딩 목록: 아홉 개, 처음부터 고른 것은 세 개, 이름이 겹치지 않는다", () => {
  const choices = onboardingChoices(["산책하기", "약 먹기"]);
  assert.equal(choices.length, 6);
  assert.equal(choices.filter((c) => c.preselected).length, 3);
  assert.equal(new Set(choices.map((c) => c.name)).size, choices.length);
  // 추천 이름이 많아도 온보딩 카드는 여섯 개(2열 × 3행)다
  const base = onboardingChoices(["산책하기", "약 먹기", "혈압 재기", "스트레칭", "일기 쓰기"]);
  assert.equal(base.length, 6);
  assert.deepEqual(base.map((c) => c.name), ["물 마시기", "영양제 먹기", "안부 전화", "알림장 확인", "산책하기", "약 먹기"]);
  assert.equal(base.find((c) => c.name === "안부 전화").shareWithFamily, false);
});

test("온보딩 항목 모양: 알림은 끈 채로, 요일 배열은 따로 복사된다", () => {
  const choice = onboardingChoices([]).find((c) => c.name === "알림장 확인");
  const item = onboardingItem(choice);
  assert.equal(item.alarm, false);
  assert.deepEqual(item.days, WEEKDAYS);
  item.days.push("sat");
  assert.equal(choice.days.length, 5);
});

test("안부 전화 항목 찾기: 이름에 '안부 전화'가 들고 오늘 해당하는 것", () => {
  assert.equal(CALL_ITEM_KEYWORD, "안부 전화");
  const items = [
    { id: "x", name: "산책 30분", days: ALL },
    { id: "y", name: "부모님께 안부 전화", days: ALL },
  ];
  assert.equal(findCallItem(items, "2026-11-02").id, "y");
  assert.equal(findCallItem([{ id: "z", name: "안부 전화", days: ["sat"] }], "2026-11-02"), null);
  assert.equal(findCallItem([], "2026-11-02"), null);
});

test("이야깃거리: 완료한 것을 최대 두 개, '…하셨어요 / …여쭤보세요' 형식", () => {
  const rows = [
    { id: "a", name: "산책 30분", type: "check", goal: 1, unit: "", entry: { done: true, doneAt: "10:12" } },
    { id: "b", name: "혈압약 먹기", type: "check", goal: 1, unit: "", entry: { done: true, doneAt: "08:30" } },
    { id: "c", name: "스트레칭", type: "check", goal: 1, unit: "", entry: { done: true, doneAt: "11:00" } },
  ];
  const points = talkingPoints(rows);
  assert.equal(points.length, 2);
  assert.deepEqual(points[0], { say: "오늘 산책 30분 하셨어요", ask: "어디로 다녀오셨는지 여쭤보세요" });
  assert.deepEqual(points[1], { say: "오전 8:30에 혈압약 드셨어요", ask: "요즘 몸은 어떠신지 물어보세요" });
});

test("이야깃거리: 횟수 항목 완료, 완료가 없을 때 기록 없는 항목, 기록이 전혀 없을 때", () => {
  const water = { id: "w", name: "물 마시기", type: "count", goal: 8, unit: "잔", entry: { count: 8, done: true, doneAt: "15:20" } };
  assert.deepEqual(talkingPoints([water]), [{ say: "물 마시기 목표를 채우셨어요", ask: "물은 잘 드시는지 여쭤보세요" }]);
  const pending = { id: "p", name: "걷기", type: "check", goal: 1, unit: "", entry: { done: false } };
  assert.deepEqual(talkingPoints([pending]), [
    { say: "걷기 기록이 아직 없어요", ask: "그 일은 잘 챙기고 계신지 여쭤보세요" },
  ]);
  assert.deepEqual(talkingPoints([]), [
    { say: "오늘 기록이 아직 없어요", ask: "오늘 하루 어떻게 지내셨는지 여쭤보세요" },
  ]);
});

