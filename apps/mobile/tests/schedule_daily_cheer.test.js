// 데일리 체크 받은 응원(메인 카드·배너) 시험: node --import ./tests/register-alias.mjs --test tests/schedule_daily_cheer.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cheerBannerText,
  cheerCaption,
  cheerCardTitle,
  pendingCheersOf,
  subjectParticle,
} from "../src/features/schedule/daily/logic.js";

const TODAY = "2026-11-02";
const received = (over) => ({ id: "x", direction: "received", fromName: "아들", kind: "love", text: "t", date: TODAY, time: "16:02", thanked: false, ...over });

test("주격 조사: 받침이 있으면 이, 없으면 가", () => {
  assert.equal(subjectParticle("아들"), "이"); // 들 받침 있음
  assert.equal(subjectParticle("딸"), "이"); // ㄹ 받침
  assert.equal(subjectParticle("아빠"), "가"); // 받침 없음
  assert.equal(subjectParticle("할머니"), "가"); // 니 받침 없음
  assert.equal(subjectParticle("Mom"), "이"); // 한글이 아니면 이
});

test("카드 제목은 'OO이 응원을 보냈어요' 형식", () => {
  assert.equal(cheerCardTitle("아들"), "아들이 응원을 보냈어요");
  assert.equal(cheerCardTitle("아빠"), "아빠가 응원을 보냈어요");
});

test("안 누른 응원만 카드로 보이고, 누른 것은 빠진다", () => {
  const list = [
    received({ id: "a", fromName: "아들" }),
    received({ id: "b", fromName: "딸", thanked: true }),
    received({ id: "c", fromName: "딸", date: "2026-11-01" }), // 어제 것은 오늘 카드에 안 나온다
    { id: "d", direction: "sent", date: TODAY, time: "10:00", thanked: false },
  ];
  assert.deepEqual(pendingCheersOf(list, TODAY).map((c) => c.id), ["a"]);
});

test("카드 아래 줄: 안 누른 수 / 오늘 받은 전체", () => {
  const list = [received({ id: "a" }), received({ id: "b", fromName: "딸", thanked: true })];
  assert.equal(cheerCaption(list, TODAY), "오늘 받은 응원 1 / 2");
  assert.equal(cheerCaption([], TODAY), "오늘 받은 응원 0 / 0");
});

test("배너 문구: 오늘 받은 응원 개수와 보낸 사람(중복 없이)", () => {
  const list = [
    received({ id: "a", fromName: "아들", thanked: true }),
    received({ id: "b", fromName: "딸", thanked: true }),
    received({ id: "c", fromName: "딸", thanked: true, time: "15:00" }),
  ];
  assert.equal(cheerBannerText(list, TODAY), "오늘 받은 응원 3개 · 아들, 딸");
});

test("닫은 카드(서버 closed)는 메인 카드에서 빠지고, 고마워 처리와 함께 배너 조건이 된다", () => {
  const list = [received({ id: "a" }), received({ id: "b", fromName: "딸", closed: true })];
  assert.deepEqual(pendingCheersOf(list, TODAY).map((c) => c.id), ["a"]);
  assert.equal(cheerCaption(list, TODAY), "오늘 받은 응원 1 / 2");
});
