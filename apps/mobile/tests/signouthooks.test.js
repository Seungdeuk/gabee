// 로그아웃 직전 훅: 등록한 순서대로 실행, 한 훅의 실패·지연이 로그아웃을 막지 않는다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { onBeforeSignOut, runBeforeSignOut } from "../src/shared/auth/signOutHooks.js";

test("hooks run in registration order and can be removed", async () => {
  const order = [];
  const offA = onBeforeSignOut(async () => order.push("a"));
  onBeforeSignOut(() => order.push("b"))();
  await runBeforeSignOut();
  assert.deepEqual(order, ["a"]);
  offA();
  await runBeforeSignOut();
  assert.deepEqual(order, ["a"]);
});

test("a failing hook does not stop the others or throw", async () => {
  const order = [];
  const offs = [
    onBeforeSignOut(() => {
      throw new Error("boom");
    }),
    onBeforeSignOut(async () => {
      throw new Error("async boom");
    }),
    onBeforeSignOut(() => order.push("ok")),
  ];
  await runBeforeSignOut();
  assert.deepEqual(order, ["ok"]);
  offs.forEach((off) => off());
});

test("a hook that never finishes is abandoned after the timeout", async () => {
  const off = onBeforeSignOut(() => new Promise(() => {}));
  const started = Date.now();
  await runBeforeSignOut(30);
  assert.ok(Date.now() - started < 1000);
  off();
});
