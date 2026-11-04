// 데일리 체크 서버 변환·온보딩 판정·가족 탭 맞춤·오류 글자 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_server.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ALL_DAYS,
  CHEER_TEXT_MAX,
  NAME_MAX,
  UNIT_MAX,
  allCheersHandled,
  cheerCaption,
  cheerTextError,
  needsOnboarding,
  normalizeTabs,
  pendingCheersOf,
  validateItem,
  withDevFamily,
} from "../src/features/schedule/daily/logic.js";
import {
  CHEER_KIND_TO_SERVER,
  cheerFromServer,
  daysToRepeat,
  entryFromServer,
  entryToServer,
  failureNotice,
  itemFromServer,
  itemToServer,
  kstClock,
  kstDateKey,
  loadErrorText,
  memberItemFromServer,
  memoFromServer,
  noteToServer,
  repeatToDays,
  summaryFromServer,
  todayKeyKST,
} from "../src/features/schedule/daily/serverMap.js";

// 한국 시간 기준 오늘 2026-11-03. 아래 응원 시각(UTC 2026-11-02 15:30)이 한국 시간 11-03 00:30 이다.
const TODAY = "2026-11-03";

test("반복 요일: 1/0 일곱 글자와 요일 키 배열이 서로 바뀐다(월~일 순서)", () => {
  assert.deepEqual(repeatToDays("1011100"), ["mon", "wed", "thu", "fri"]);
  assert.equal(daysToRepeat(["mon", "wed", "thu", "fri"]), "1011100");
  assert.equal(daysToRepeat(["sun"]), "0000001");
  assert.equal(daysToRepeat(ALL_DAYS), "1111111");
  assert.deepEqual(repeatToDays(daysToRepeat(["sat", "sun"])), ["sat", "sun"]);
});

test("한국 시간 변환: UTC 15:30 은 다음 날 00:30(한국)이다", () => {
  assert.equal(kstDateKey("2026-11-02T15:30:00Z"), "2026-11-03");
  assert.equal(kstClock("2026-11-02T15:30:00Z"), "00:30");
  assert.equal(kstDateKey("2026-11-02T15:30:00.123456+00:00"), "2026-11-03");
  assert.equal(kstClock("2026-11-02T15:30:00.123456+00:00"), "00:30");
  // 시간대 표기가 없으면 UTC 로 본다
  assert.equal(kstClock("2026-11-02T15:30:00"), "00:30");
});

test("오늘 날짜(한국 시간): 자정 경계에서 바뀐다", () => {
  assert.equal(todayKeyKST(Date.UTC(2026, 10, 2, 14, 59, 0)), "2026-11-02");
  assert.equal(todayKeyKST(Date.UTC(2026, 10, 2, 15, 0, 0)), "2026-11-03");
});

const checkRow = (over = {}) => ({
  id: "a1",
  name: "약 먹기",
  kind: 1,
  goal: null,
  unit: "",
  repeat_days: "1111111",
  shared: true,
  notify: false,
  position: 0,
  done: false,
  count: null,
  confirmed: false,
  confirmed_at: null,
  ...over,
});
const countRow = (over = {}) => ({
  id: "b1",
  name: "물 마시기",
  kind: 2,
  goal: 8,
  unit: "잔",
  repeat_days: "1111111",
  shared: true,
  notify: false,
  position: 1,
  done: null,
  count: 0,
  confirmed: false,
  confirmed_at: null,
  ...over,
});

test("한 번 체크 습관: 서버 done 과 confirmed_at(한국 시간 HH:MM)이 entry 가 된다", () => {
  const item = itemFromServer(checkRow({ done: true, confirmed: true, confirmed_at: "2026-11-02T23:10:00Z" }));
  assert.equal(item.type, "check");
  assert.equal(item.goal, 1);
  assert.equal(item.unit, "");
  assert.deepEqual(item.days, ALL_DAYS);
  assert.equal(item.shareWithFamily, true);
  assert.equal(item.alarm, false);
  assert.deepEqual(item.entry, { done: true, count: 0, doneAt: "08:10" });
  assert.deepEqual(itemFromServer(checkRow()).entry, { done: false, count: 0, doneAt: null });
});

test("횟수 습관: count 는 절대값, 목표에 닿으면 완료와 시각", () => {
  const partial = itemFromServer(countRow({ count: 5, confirmed: false, confirmed_at: "2026-11-02T01:00:00Z" }));
  assert.equal(partial.type, "count");
  assert.equal(partial.goal, 8);
  assert.equal(partial.unit, "잔");
  assert.deepEqual(partial.entry, { done: false, count: 5, doneAt: null });
  const full = itemFromServer(countRow({ count: 8, confirmed: true, confirmed_at: "2026-11-02T10:12:00Z" }));
  assert.deepEqual(full.entry, { done: true, count: 8, doneAt: "19:12" });
});

test("요일: 서버 repeat_days 가 화면 요일 목록이 되고 shared·notify 는 공유·알림 표시가 된다", () => {
  const item = itemFromServer(checkRow({ repeat_days: "1000100", shared: false, notify: true }));
  assert.deepEqual(item.days, ["mon", "fri"]);
  assert.equal(item.shareWithFamily, false);
  assert.equal(item.alarm, true);
});

test("화면 항목 → 서버 본문: 한 번 체크는 목표·단위가 null·빈 글자, 횟수는 목표와 단위", () => {
  const check = itemToServer({ name: "영양제", type: "check", goal: 1, unit: "", days: ["mon", "tue"], alarm: false, shareWithFamily: true });
  assert.deepEqual(check, { name: "영양제", kind: 1, goal: null, unit: "", repeat_days: "1100000", shared: true, notify: false });
  const count = itemToServer({ name: "물", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: true, shareWithFamily: false });
  assert.deepEqual(count, { name: "물", kind: 2, goal: 8, unit: "잔", repeat_days: "1111111", shared: false, notify: true });
});

test("기록 저장 본문: 한 번 체크는 done, 횟수는 count", () => {
  assert.deepEqual(entryToServer({ type: "check" }, { done: true, count: 0, doneAt: "08:00" }), { done: true });
  assert.deepEqual(entryToServer({ type: "count" }, { done: false, count: 5, doneAt: null }), { count: 5 });
});

test("서버 기록 entry: 날짜가 지난 기록은 서버가 미완료로 보내므로 빈 entry 가 된다", () => {
  assert.deepEqual(entryFromServer({ kind: 1, done: false, confirmed_at: null }), { done: false, count: 0, doneAt: null });
  assert.deepEqual(entryFromServer({ kind: 2, count: 0, confirmed: false, confirmed_at: null }), { done: false, count: 0, doneAt: null });
});

test("가족 오늘 습관 줄: 서버가 거른 것이라 오늘 요일로 보이고 기록이 entry 가 된다", () => {
  const row = memberItemFromServer({
    id: "x",
    name: "산책",
    kind: 1,
    goal: null,
    unit: "",
    done: true,
    count: null,
    confirmed: true,
    confirmed_at: "2026-11-02T01:30:00Z",
  });
  assert.equal(row.shareWithFamily, true);
  assert.deepEqual(row.days, ALL_DAYS);
  assert.deepEqual(row.entry, { done: true, count: 0, doneAt: "10:30" });
});

test("응원 종류 ↔ 서버 숫자: 사랑해요 1, 최고예요 2, 잘하셨어요 3", () => {
  assert.deepEqual(CHEER_KIND_TO_SERVER, { love: 1, best: 2, well: 3 });
  const row = {
    id: "c1",
    from_user_id: "u1",
    from_name: "아들",
    to_user_id: "u2",
    to_name: "나",
    kind: 2,
    message: "최고예요",
    chat_left: true,
    sent_at: "2026-11-02T15:30:00Z",
    thanked_at: null,
    closed: false,
    closed_at: null,
  };
  const cheer = cheerFromServer(row, "received");
  assert.equal(cheer.kind, "best");
  assert.equal(cheer.date, TODAY);
  assert.equal(cheer.time, "00:30");
  assert.equal(cheer.thanked, false);
  assert.equal(cheer.closed, false);
  assert.equal(cheer.groupChat, true);
  assert.equal(cheer.fromName, "아들");
});

test("오늘 받은 응원: 한국 날짜 기준 보낸 시각으로 오늘을 정하고, 고마워·닫기 된 것은 카드에서 빠진다", () => {
  const base = {
    from_user_id: "u1",
    from_name: "아들",
    to_user_id: "me",
    to_name: "나",
    kind: 1,
    message: "m",
    chat_left: false,
    thanked_at: null,
    closed: false,
    closed_at: null,
  };
  const todayOpen = cheerFromServer({ ...base, id: "t1", sent_at: "2026-11-02T15:30:00Z" }, "received"); // 한국 11-03 00:30
  const yesterday = cheerFromServer({ ...base, id: "y1", sent_at: "2026-11-02T14:00:00Z" }, "received"); // 한국 11-02 23:00
  const thanked = cheerFromServer({ ...base, id: "t2", sent_at: "2026-11-02T15:40:00Z", thanked_at: "2026-11-02T16:00:00Z" }, "received");
  const closedOne = cheerFromServer({ ...base, id: "t3", sent_at: "2026-11-02T15:45:00Z", closed: true }, "received");
  const list = [todayOpen, yesterday, thanked, closedOne];
  assert.deepEqual(pendingCheersOf(list, TODAY).map((c) => c.id), ["t1"]);
  assert.equal(cheerCaption(list, TODAY), "오늘 받은 응원 1 / 3");
  assert.equal(allCheersHandled(list, TODAY), false);
  assert.equal(allCheersHandled([thanked, closedOne], TODAY), true);
});

test("온보딩 판정: 서버에 습관이 없고 완료 표시가 거짓일 때만 온보딩", () => {
  assert.equal(needsOnboarding([], false), true);
  assert.equal(needsOnboarding([], true), false);
  assert.equal(needsOnboarding([{ id: "a" }], false), false);
  assert.equal(needsOnboarding([{ id: "a" }], true), false);
});

test("가족 탭 맞춤: 새 가족은 뒤에 붙고, 없어진 가족은 빠지며, 숨김도 같이 맞춘다", () => {
  const saved = { order: ["mom", "gone", "dad"], hidden: ["gone", "dad"] };
  const tabs = normalizeTabs(saved, ["mom", "dad", "new"]);
  assert.deepEqual(tabs.order, ["mom", "dad", "new"]);
  assert.deepEqual(tabs.hidden, ["dad"]);
  assert.deepEqual(normalizeTabs(null, ["mom", "dad"]), { order: ["mom", "dad"], hidden: [] });
  assert.deepEqual(normalizeTabs({ order: ["x", "mom"] }, ["mom"]), { order: ["mom"], hidden: [] });
});

test("가족 요약: 서버 user_id 를 앱 id 로 바꾼다(나는 me, 엄마는 mom)", () => {
  const toApp = (userId) => ({ "me-user": "me", "mom-user": "mom" })[userId] ?? userId;
  assert.deepEqual(summaryFromServer({ user_id: "mom-user", name: "엄마", total: 3, done: 1 }, toApp), {
    id: "mom",
    name: "엄마",
    total: 3,
    done: 1,
  });
  assert.equal(summaryFromServer({ user_id: "me-user", name: "나", total: 0, done: 0 }, toApp).id, "me");
  assert.equal(summaryFromServer({ user_id: "u9", name: "딸", total: 1, done: 0 }, toApp).id, "u9");
});

test("가상 가족: 개발 빌드에서 실제 가족이 없을 때만 덧붙고 hasAccount 가 false 다", () => {
  const onlyMe = [{ id: "me", name: "나", hasAccount: true }];
  assert.equal(withDevFamily(onlyMe, false), onlyMe);
  const added = withDevFamily(onlyMe, true);
  assert.ok(added.some((m) => m.id === "mom" && m.hasAccount === false));
  const withReal = [
    { id: "me", name: "나", hasAccount: true },
    { id: "u-son", name: "아들", hasAccount: true },
  ];
  assert.equal(withDevFamily(withReal, true), withReal);
});

test("오류 글자: 준비 중(503)과 연결 실패를 나누고, 안내 팝업 제목을 호출한 쪽이 정한다", () => {
  assert.equal(loadErrorText({ status: 503 }), "준비 중이에요");
  assert.equal(loadErrorText({ status: 0 }), "서버에 연결하지 못했어요");
  assert.equal(loadErrorText(undefined), "서버에 연결하지 못했어요");
  assert.deepEqual(failureNotice({ status: 503 }), { title: "준비 중이에요", body: "잠시 후 다시 해 주세요" });
  assert.equal(failureNotice({ status: 400 }, "지우지 못했어요").title, "지우지 못했어요");
  assert.equal(failureNotice({ status: 400 }).title, "저장하지 못했어요");
});

test("앱 글자 수 상한(사용자 결정): 이름 20, 단위 10, 응원 한마디 50, 서버 한도보다 좁다", () => {
  assert.equal(NAME_MAX, 20);
  assert.equal(UNIT_MAX, 10);
  assert.equal(CHEER_TEXT_MAX, 50);
});

test("이름 검사: 20자까지는 통과, 21자부터 안내", () => {
  const ok = { name: "가".repeat(20), type: "check", days: ALL_DAYS };
  assert.equal(validateItem(ok).ok, true);
  const over = validateItem({ ...ok, name: "가".repeat(21) });
  assert.equal(over.ok, false);
  assert.equal(over.error, "이름은 20자까지 쓸 수 있어요");
});

test("단위 검사: 단위가 10자까지는 통과, 11자부터 인라인 오류(마침표 없음)", () => {
  const base = { name: "물", type: "count", days: ALL_DAYS };
  assert.equal(validateItem({ ...base, goalText: `8${"잔".repeat(10)}` }).ok, true);
  const over = validateItem({ ...base, goalText: `8${"잔".repeat(11)}` });
  assert.equal(over.ok, false);
  assert.equal(over.error, "단위는 10자까지 쓸 수 있어요");
});

test("한 번 체크는 단위 검사를 하지 않는다(목표·단위 칸이 없다)", () => {
  assert.equal(validateItem({ name: "약", type: "check", goalText: "x".repeat(50), days: ALL_DAYS }).ok, true);
});

test("응원 한마디: 50자까지 통과, 51자부터 안내", () => {
  assert.equal(cheerTextError("가".repeat(50)), "");
  assert.equal(cheerTextError("가".repeat(51)), "한마디는 50자까지 쓸 수 있어요");
});

test("422(입력 모양·글자 수 초과)는 글자 수 확인 안내로 구분한다", () => {
  assert.deepEqual(failureNotice({ status: 422 }), { title: "저장하지 못했어요", body: "입력한 글자 수를 확인해 주세요" });
  assert.equal(failureNotice({ status: 422 }, "보내지 못했어요").title, "보내지 못했어요");
});

test("400 은 서버가 준 이유(범위 밖 날짜 등)를 안내 본문으로 보이고, 이유가 없으면 기본 문장을 쓴다", () => {
  const error = { status: 400, message: "기록은 오늘부터 7일 전까지의 날짜만 볼 수 있어요" };
  assert.deepEqual(failureNotice(error), { title: "저장하지 못했어요", body: "기록은 오늘부터 7일 전까지의 날짜만 볼 수 있어요" });
  assert.equal(failureNotice({ status: 400 }).body, "잠시 후 다시 해 주세요");
});

test("서버 메모 → 화면 메모: 글자가 있을 때만 메모가 있고 공유 표시를 옮긴다", () => {
  assert.equal(memoFromServer({ note: null, note_shared: false }), undefined);
  assert.deepEqual(memoFromServer({ note: "혈압 120/80", note_shared: true }), { note: "혈압 120/80", noteShared: true });
});

test("습관 한 줄: applies·메모·updated_at 을 옮기고, 지난 날짜의 기록을 entry 로 바꾼다", () => {
  const item = itemFromServer(
    checkRow({
      applies: false,
      note: "식후에 먹었어요",
      note_shared: true,
      updated_at: "2026-11-02T15:30:00Z",
      done: true,
      confirmed: true,
      confirmed_at: "2026-11-02T01:00:00Z",
    }),
  );
  assert.equal(item.applies, false);
  assert.deepEqual(item.memo, { note: "식후에 먹었어요", noteShared: true });
  assert.deepEqual(item.entry, { done: true, count: 0, doneAt: "10:00" }); // 한국 시간 10:00
  assert.equal(item.updatedAt, "2026-11-02T15:30:00Z");
  const plain = itemFromServer(countRow({ applies: true }));
  assert.equal(plain.applies, true);
  assert.equal(plain.memo, undefined);
});

test("메모 요청 본문: 저장은 note·note_shared, 지우기는 note 를 null 로 보내고 공유는 끈다", () => {
  assert.deepEqual(noteToServer({ note: "식후", noteShared: true }), { note: "식후", note_shared: true });
  assert.deepEqual(noteToServer(null), { note: null, note_shared: false });
});

test("가족 줄의 메모: 서버가 공개로 준 note 를 옮기고, 없으면 null 이다", () => {
  const base = { id: "x", name: "혈압약", kind: 1, goal: null, unit: "", done: true, count: null, confirmed: true, confirmed_at: null };
  assert.equal(memberItemFromServer({ ...base, note: "괜찮았어요" }).note, "괜찮았어요");
  assert.equal(memberItemFromServer({ ...base, note: null }).note, null);
});
