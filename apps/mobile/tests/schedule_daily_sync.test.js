// 데일리 체크 저장 보조 시험(디바운스·줄 세우기·롤백 판정·기록 맞춤): node --import ./tests/register-alias.mjs --test tests/schedule_daily_sync.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { createEntrySync } from "../src/features/schedule/daily/entrySync.js";
import { createDebouncedSaver, createKeyedQueue, isLatestChange } from "../src/features/schedule/daily/sync.js";

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
    count: () => pending.size,
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

const checkItem = { id: "a", name: "영양제", type: "check", goal: 1, unit: "", days: [], alarm: false, shareWithFamily: true };
const countItem = { id: "b", name: "물", type: "count", goal: 8, unit: "잔", days: [], alarm: false, shareWithFamily: true };

test("디바운스: 여러 번 바꾸면 마지막 값만 시간이 지난 뒤 한 번 보낸다", () => {
  const timers = fakeTimers();
  const saved = [];
  const saver = createDebouncedSaver({ delay: 400, save: (key, value) => saved.push([key, value]), setTimer: timers.setTimer, clearTimer: timers.clearTimer });
  saver.set("b", 1);
  saver.set("b", 2);
  saver.set("b", 3);
  assert.equal(timers.count(), 1); // 이전 예약은 지워진다
  assert.deepEqual(saved, []);
  timers.run();
  assert.deepEqual(saved, [["b", 3]]);
  assert.equal(saver.has("b"), false);
});

test("디바운스: flushAll 은 기다리지 않고 대기 중인 값을 바로 보낸다", async () => {
  const timers = fakeTimers();
  const saved = [];
  const saver = createDebouncedSaver({ save: (key, value) => saved.push([key, value]), setTimer: timers.setTimer, clearTimer: timers.clearTimer });
  saver.set("b", 5);
  await saver.flushAll();
  assert.deepEqual(saved, [["b", 5]]);
  assert.equal(timers.count(), 0);
  timers.run(); // 이미 보낸 것은 다시 보내지 않는다
  assert.equal(saved.length, 1);
});

test("줄 세우기: 같은 항목의 작업은 앞의 것이 끝난 뒤에 실행한다", async () => {
  const enqueue = createKeyedQueue();
  const log = [];
  const first = deferred();
  enqueue("a", async () => {
    log.push("1 시작");
    await first.promise;
    log.push("1 끝");
  });
  const second = enqueue("a", async () => {
    log.push("2 시작");
  });
  await tick();
  assert.deepEqual(log, ["1 시작"]);
  first.resolve();
  await second;
  assert.deepEqual(log, ["1 시작", "1 끝", "2 시작"]);
});

test("줄 세우기: 다른 항목은 서로 기다리지 않고, 앞 작업이 실패해도 뒤 작업은 간다", async () => {
  const enqueue = createKeyedQueue();
  const stuck = deferred();
  enqueue("a", () => stuck.promise);
  const other = await enqueue("b", () => "b 완료");
  assert.equal(other, "b 완료");
  const failed = enqueue("c", async () => {
    throw new Error("실패");
  });
  await assert.rejects(failed, /실패/);
  assert.equal(await enqueue("c", () => "다음 작업"), "다음 작업");
  stuck.resolve();
});

test("롤백 판정: 요청 번호가 최근 번호와 같을 때만 응답을 화면에 반영한다", () => {
  assert.equal(isLatestChange(3, 3), true);
  assert.equal(isLatestChange(2, 3), false);
});

test("한 번 체크: 바로 화면에 보이고, 서버 응답의 기록으로 맞춘다", async () => {
  const shown = [];
  const sync = createEntrySync({
    send: async (item, entry) => ({ ...item, entry: { ...entry, doneAt: "08:10" } }),
    show: (id, entry) => shown.push([id, entry]),
    onError: () => assert.fail("실패하면 안 된다"),
  });
  sync.seed({ a: { done: false, count: 0, doneAt: null } });
  sync.change(checkItem, { done: true, count: 0, doneAt: "08:09" });
  assert.deepEqual(shown[0], ["a", { done: true, count: 0, doneAt: "08:09" }]); // 누르는 즉시
  await tick();
  assert.deepEqual(shown[shown.length - 1], ["a", { done: true, count: 0, doneAt: "08:10" }]); // 서버 응답
});

test("낙관적 갱신 롤백: 저장이 실패하면 서버가 마지막으로 확인한 값으로 되돌리고 알린다", async () => {
  const shown = [];
  const errors = [];
  const sync = createEntrySync({
    send: async () => {
      throw new Error("연결 실패");
    },
    show: (id, entry) => shown.push([id, entry]),
    onError: (error) => errors.push(error.message),
  });
  const committed = { done: false, count: 0, doneAt: null };
  sync.seed({ a: committed });
  sync.change(checkItem, { done: true, count: 0, doneAt: "08:09" });
  await tick();
  assert.deepEqual(shown[shown.length - 1], ["a", committed]);
  assert.deepEqual(errors, ["연결 실패"]);
  assert.deepEqual(sync.valueOf("a"), committed);
});

test("롤백하지 않음: 실패한 요청 뒤에 더 새 변경이 있으면 그 변경이 화면을 정한다", async () => {
  const shown = [];
  const errors = [];
  const sends = [];
  const sync = createEntrySync({
    send: (item, entry) => {
      const d = deferred();
      sends.push({ d, entry });
      return d.promise.then(() => ({ ...item, entry }));
    },
    show: (id, entry) => shown.push(entry),
    onError: (error) => errors.push(error),
  });
  sync.seed({ a: { done: false, count: 0, doneAt: null } });
  sync.change(checkItem, { done: true, count: 0, doneAt: "08:00" });
  sync.change(checkItem, { done: false, count: 0, doneAt: null });
  await tick();
  assert.equal(sends.length, 1); // 같은 항목은 앞의 저장이 끝나야 다음을 보낸다
  const before = shown.length;
  sends[0].d.reject(new Error("옛 요청 실패"));
  await tick();
  assert.equal(shown.length, before); // 옛 실패는 화면을 되돌리지 않는다
  assert.equal(errors.length, 0);
  assert.equal(sync.valueOf("a").done, false);
  await tick();
  assert.equal(sends.length, 2); // 뒤의 변경이 이제 보내진다
  sends[1].d.resolve();
  await tick();
  assert.equal(sync.valueOf("a").done, false);
});

test("횟수 디바운스: 연타하면 화면은 바로 바뀌고 서버에는 마지막 값 한 번만 간다", async () => {
  const timers = fakeTimers();
  const sent = [];
  const sync = createEntrySync({
    send: async (item, entry) => {
      sent.push(entry.count);
      return { ...item, entry };
    },
    show: () => {},
    onError: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  sync.seed({ b: { done: false, count: 0, doneAt: null } });
  sync.change(countItem, { done: false, count: 1, doneAt: null }, { debounced: true });
  sync.change(countItem, { done: false, count: 2, doneAt: null }, { debounced: true });
  sync.change(countItem, { done: false, count: 3, doneAt: null }, { debounced: true });
  assert.equal(sync.valueOf("b").count, 3);
  assert.deepEqual(sent, []);
  timers.run();
  await tick();
  assert.deepEqual(sent, [3]);
});

test("횟수 flushAll: 화면을 떠나기 전에 남은 값을 바로 보낸다", async () => {
  const timers = fakeTimers();
  const sent = [];
  const sync = createEntrySync({
    send: async (item, entry) => {
      sent.push(entry.count);
      return { ...item, entry };
    },
    show: () => {},
    onError: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  sync.seed({ b: { done: false, count: 0, doneAt: null } });
  sync.change(countItem, { done: false, count: 4, doneAt: null }, { debounced: true });
  await sync.flushAll();
  assert.deepEqual(sent, [4]);
});

test("횟수 롤백: 디바운스된 저장이 실패하면 마지막으로 확인한 횟수로 돌아간다", async () => {
  const timers = fakeTimers();
  const shown = [];
  const sync = createEntrySync({
    send: async () => {
      throw new Error("서버 오류");
    },
    show: (id, entry) => shown.push(entry),
    onError: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  sync.seed({ b: { done: false, count: 2, doneAt: null } });
  sync.change(countItem, { done: false, count: 5, doneAt: null }, { debounced: true });
  timers.run();
  await tick();
  assert.equal(shown[shown.length - 1].count, 2);
  assert.equal(sync.valueOf("b").count, 2);
});

test("기록 맞춤: 저장 중인 항목은 화면 값을 두고, 나머지는 서버 값을 쓴다", () => {
  const timers = fakeTimers();
  const sync = createEntrySync({
    send: async (item, entry) => ({ ...item, entry }),
    show: () => {},
    onError: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  sync.seed({ b: { done: false, count: 0, doneAt: null }, a: { done: false, count: 0, doneAt: null } });
  sync.change(countItem, { done: false, count: 4, doneAt: null }, { debounced: true });
  const merged = sync.seed({ b: { done: false, count: 1, doneAt: null }, a: { done: true, count: 0, doneAt: "09:00" } });
  assert.equal(merged.b.count, 4); // 아직 저장 전인 값은 그대로
  assert.equal(merged.a.done, true); // 나머지는 서버 값
});
