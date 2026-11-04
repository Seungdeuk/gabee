// 데일리 체크 날짜별 저장 시험(지난 날 기록·메모의 낙관 갱신·롤백·줄 세우기, 오늘은 저장 보조로 넘김): node --import ./tests/register-alias.mjs --test tests/schedule_daily_store.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { createDayStore } from "../src/features/schedule/daily/dayStore.js";

const TODAY = "2026-11-03";
const PAST = "2026-11-01";

const check = { id: "a", name: "영양제", type: "check", goal: 1, unit: "", days: [] };
const count = { id: "b", name: "물", type: "count", goal: 8, unit: "잔", days: [] };

// 가짜 시계: 예약은 쌓아 두고, run() 을 부르면 지금까지 예약된 것을 모두 실행한다.
function fakeTimers() {
  let nextId = 0;
  const pending = new Map();
  return {
    setTimer(fn) {
      nextId += 1;
      pending.set(nextId, fn);
      return nextId;
    },
    clearTimer(id) {
      pending.delete(id);
    },
    run() {
      const all = [...pending.values()];
      pending.clear();
      all.forEach((fn) => fn());
    },
  };
}

// 바깥에서 끝낼 수 있는 약속(서버 응답을 흉내낸다).
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

// 오늘 저장 보조(entrySync) 흉내: 값을 기억하고 바꾼 호출을 적는다.
function fakeSync() {
  const values = {};
  const changes = [];
  return {
    values,
    changes,
    valueOf: (id) => values[id],
    change(item, entry, options) {
      values[item.id] = entry;
      changes.push({ id: item.id, entry, options });
    },
    flushAll: async () => {},
  };
}

function makeStore(overrides = {}) {
  const timers = fakeTimers();
  const sync = fakeSync();
  const errors = [];
  const changed = { n: 0 };
  const store = createDayStore({
    getDeps: () => ({ today: TODAY, sync }),
    saveEntry: overrides.saveEntry ?? (async (item, entry) => ({ ...item, entry })),
    saveNote: overrides.saveNote ?? (async (item, date, memo) => ({ ...item, memo: memo ?? undefined })),
    onChange: () => {
      changed.n += 1;
    },
    onError: (error) => errors.push(error.message),
    delay: 400,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  return { store, sync, timers, errors, changed };
}

const pastRow = (over = {}) => ({ ...check, entry: { done: false, count: 0, doneAt: null }, ...over });

test("지난 날 체크: 누르는 즉시 그 날짜에 보이고, 서버 응답의 기록으로 맞춘다", async () => {
  const sent = [];
  const { store } = makeStore({
    saveEntry: async (item, entry, date) => {
      sent.push({ id: item.id, date, done: entry.done });
      return { ...item, entry: { ...entry, doneAt: "08:10" } };
    },
  });
  store.seedEntries(PAST, [pastRow()]);
  store.checkItem(check, PAST);
  assert.equal(store.pastEntryOf("a", PAST).done, true); // 누르는 즉시
  await tick();
  assert.deepEqual(sent, [{ id: "a", date: PAST, done: true }]); // 날짜를 함께 보낸다
  assert.equal(store.pastEntryOf("a", PAST).doneAt, "08:10"); // 서버 응답으로 맞춘다
});

test("지난 날 체크 실패: 서버가 마지막으로 확인한 기록으로 되돌리고 알린다", async () => {
  const { store, errors } = makeStore({
    saveEntry: async () => {
      throw new Error("서버 연결 실패");
    },
  });
  const committed = { done: false, count: 0, doneAt: null };
  store.seedEntries(PAST, [pastRow({ entry: committed })]);
  store.checkItem(check, PAST);
  await tick();
  assert.deepEqual(store.pastEntryOf("a", PAST), committed);
  assert.deepEqual(errors, ["서버 연결 실패"]);
});

test("지난 날 횟수: +/− 연타는 디바운스로 마지막 값만 한 번 보낸다", async () => {
  const sent = [];
  const { store, timers } = makeStore({
    saveEntry: async (item, entry, date) => {
      sent.push({ date, count: entry.count });
      return { ...item, entry };
    },
  });
  store.seedEntries(PAST, [pastRow({ ...count, entry: { done: false, count: 2, doneAt: null } })]);
  store.stepItem(count, PAST, 1);
  store.stepItem(count, PAST, 1);
  store.stepItem(count, PAST, 1);
  assert.equal(store.pastEntryOf("b", PAST).count, 5); // 화면은 바로 5
  assert.deepEqual(sent, []); // 아직 안 보냄
  timers.run();
  await tick();
  assert.deepEqual(sent, [{ date: PAST, count: 5 }]); // 마지막 값 한 번
});

test("지난 날 기록 응답은 메모를 지우지 않는다(기록과 메모는 따로 보낸다)", async () => {
  const memo = { note: "식후에 먹었어요", noteShared: false };
  const { store } = makeStore({
    saveEntry: async (item, entry) => ({ ...item, entry }), // 응답에는 메모가 없다
  });
  store.seedMemos(PAST, [pastRow({ memo })]);
  store.seedEntries(PAST, [pastRow({ memo })]);
  store.checkItem(check, PAST);
  await tick();
  assert.deepEqual(store.memoOf("a", PAST), memo);
});

test("지난 날 목록을 받으면 기록을 맞춘다: 저장 중인 항목은 화면 값을 우선한다", async () => {
  const pending = deferred();
  const { store } = makeStore({ saveEntry: () => pending.promise });
  store.seedEntries(PAST, [pastRow()]);
  store.checkItem(check, PAST); // 저장 중
  store.seedEntries(PAST, [pastRow({ entry: { done: false, count: 0, doneAt: null } })]); // 서버는 아직 미완료
  assert.equal(store.pastEntryOf("a", PAST).done, true); // 화면 값 유지
  pending.resolve({ ...check, entry: { done: true, count: 0, doneAt: "09:00" } });
  await tick();
  assert.equal(store.pastEntryOf("a", PAST).doneAt, "09:00");
});

test("메모 seed: 서버가 준 메모를 그날에 보이고, 메모가 없는 항목은 비어 있다", () => {
  const { store } = makeStore();
  store.seedMemos(PAST, [
    { ...check, memo: { note: "120/80", noteShared: true } },
    { ...count, memo: undefined },
  ]);
  assert.deepEqual(store.memoOf("a", PAST), { note: "120/80", noteShared: true });
  assert.equal(store.memoOf("b", PAST), undefined);
  assert.equal(store.memoOf("a", TODAY), undefined); // 다른 날짜에는 없다
});

test("메모 저장: 누르는 즉시 보이고, 서버 호출에 날짜와 메모를 보내고, 응답의 메모로 맞춘다", async () => {
  const calls = [];
  const { store, errors } = makeStore({
    saveNote: async (item, date, memo) => {
      calls.push({ id: item.id, date, memo });
      return { ...item, memo: { note: memo.note, noteShared: memo.noteShared } };
    },
  });
  const memo = { note: "메모", noteShared: false };
  store.saveMemo(check, PAST, memo);
  assert.deepEqual(store.memoOf("a", PAST), memo);
  await tick();
  assert.deepEqual(calls, [{ id: "a", date: PAST, memo }]);
  assert.deepEqual(store.memoOf("a", PAST), memo);
  assert.deepEqual(errors, []);
});

test("메모 지우기: null 을 보내고 화면에서 지운다(오늘 날짜도 같다)", async () => {
  const calls = [];
  const { store } = makeStore({
    saveNote: async (item, date, memo) => {
      calls.push(memo);
      return { ...item, memo: undefined };
    },
  });
  store.seedMemos(TODAY, [{ ...check, memo: { note: "있던 메모", noteShared: true } }]);
  store.saveMemo(check, TODAY, null);
  assert.equal(store.memoOf("a", TODAY), undefined);
  await tick();
  assert.deepEqual(calls, [null]);
  assert.equal(store.memoOf("a", TODAY), undefined);
});

test("메모 저장 실패: 서버가 마지막으로 확인한 메모로 되돌리고 알린다", async () => {
  const old = { note: "예전 메모", noteShared: false };
  const { store, errors } = makeStore({
    saveNote: async () => {
      throw new Error("서버 오류");
    },
  });
  store.seedMemos(PAST, [{ ...check, memo: old }]);
  store.saveMemo(check, PAST, { note: "새 메모", noteShared: true });
  await tick();
  assert.deepEqual(store.memoOf("a", PAST), old);
  assert.deepEqual(errors, ["서버 오류"]);
});

test("메모 줄 세우기: 앞 저장이 실패해도 최근 변경만 화면을 정하고, 옛 실패는 되돌리지 않는다", async () => {
  const sent = [];
  const { store, errors } = makeStore({
    saveNote: (item, date, memo) => {
      const d = deferred();
      sent.push({ d, memo });
      return d.promise;
    },
  });
  const first = { note: "첫 메모", noteShared: false };
  const second = { note: "둘째 메모", noteShared: false };
  store.saveMemo(check, PAST, first);
  store.saveMemo(check, PAST, second);
  await tick();
  assert.equal(sent.length, 1); // 둘째는 첫째가 끝날 때까지 기다린다
  sent[0].d.reject(new Error("옛 실패"));
  await tick();
  await tick();
  assert.equal(sent.length, 2);
  assert.deepEqual(store.memoOf("a", PAST), second); // 옛 실패로 되돌리지 않는다
  sent[1].d.resolve({ ...check, memo: second });
  await tick();
  assert.deepEqual(store.memoOf("a", PAST), second);
  assert.deepEqual(errors, []);
});

test("메모 저장 중 목록을 다시 받아도 저장 중인 메모는 화면 값을 지킨다", async () => {
  const pending = deferred();
  const { store } = makeStore({ saveNote: () => pending.promise });
  store.seedMemos(PAST, [{ ...check }]);
  const mine = { note: "내가 쓰는 중", noteShared: false };
  store.saveMemo(check, PAST, mine);
  store.seedMemos(PAST, [{ ...check, memo: { note: "서버 옛 값", noteShared: false } }]);
  assert.deepEqual(store.memoOf("a", PAST), mine);
  pending.resolve({ ...check, memo: mine });
  await tick();
  assert.deepEqual(store.memoOf("a", PAST), mine);
});

test("오늘 기록은 저장 보조(sync)에 넘기고, 지난 날 저장 값에는 넣지 않는다", () => {
  const { store, sync } = makeStore();
  store.checkItem(check, TODAY);
  store.stepItem(count, TODAY, 1);
  assert.equal(sync.changes.length, 2);
  assert.equal(sync.changes[0].id, "a");
  assert.equal(sync.changes[0].options, undefined);
  assert.deepEqual(sync.changes[1].options, { debounced: true });
  assert.equal(store.pastEntryOf("a", TODAY), undefined);
});

test("대기 중인 지난 날 횟수는 flushAll 로 기다리지 않고 바로 보낸다", async () => {
  const sent = [];
  const { store } = makeStore({
    saveEntry: async (item, entry, date) => {
      sent.push({ date, count: entry.count });
      return { ...item, entry };
    },
  });
  store.seedEntries(PAST, [pastRow({ ...count, entry: { done: false, count: 1, doneAt: null } })]);
  store.stepItem(count, PAST, 2);
  assert.deepEqual(sent, []);
  await store.flushAll();
  assert.deepEqual(sent, [{ date: PAST, count: 3 }]);
});
