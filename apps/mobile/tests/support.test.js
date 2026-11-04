// 고객센터(문의·신고): 입력 검사·문구·API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { KIND_META, routeFor } from "../src/features/notifications/kinds.js";
import { BODY_MAX, TITLE_MAX, dateText, supportErrorMessage, ticketView, validateTicket } from "../src/features/support/messages.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";
// 서버 주소는 불러올 때 읽으므로 환경 변수를 정한 뒤에 가져온다
const { createTicket, listMyTickets } = await import("../src/features/support/api.js");

const realFetch = globalThis.fetch;
const calls = [];
beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    return new Response(JSON.stringify({ rows: [], id: "t1" }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("API 경로: 보내기는 POST /support/tickets 에 종류·제목·내용만, 내 문의는 GET /support/tickets/mine", async () => {
  await createTicket({ kind: "report", title: "신고해요", body: "내용이에요" });
  assert.equal(calls.at(-1).method, "POST");
  assert.equal(calls.at(-1).url, "http://api.test/support/tickets");
  assert.deepEqual(JSON.parse(calls.at(-1).body), { kind: "report", title: "신고해요", body: "내용이에요" });
  await listMyTickets();
  assert.equal(calls.at(-1).method, "GET");
  assert.equal(calls.at(-1).url, "http://api.test/support/tickets/mine");
});

test("입력 검사: 앞뒤 공백을 지우고 종류·제목·내용이 있어야 한다", () => {
  assert.deepEqual(validateTicket({ kind: "inquiry", title: "  제목 ", body: " 내용 " }), { ok: true, value: { kind: "inquiry", title: "제목", body: "내용" } });
  const empty = validateTicket({ kind: "x", title: "  ", body: "" });
  assert.equal(empty.ok, false);
  assert.deepEqual(Object.keys(empty.errors).sort(), ["body", "kind", "title"]);
  assert.equal(validateTicket({ kind: "report", title: null, body: undefined }).ok, false);
});

test("입력 검사: 제목 100자·내용 2000자까지(서버 규칙과 같다)", () => {
  assert.equal(validateTicket({ kind: "inquiry", title: "가".repeat(TITLE_MAX), body: "나".repeat(BODY_MAX) }).ok, true);
  assert.match(validateTicket({ kind: "inquiry", title: "가".repeat(TITLE_MAX + 1), body: "내용" }).errors.title, /100자/);
  assert.match(validateTicket({ kind: "inquiry", title: "제목", body: "나".repeat(BODY_MAX + 1) }).errors.body, /2000자/);
});

test("오류 문구: 상태별 안내이고 쓴 내용은 넣지 않는다", () => {
  assert.match(supportErrorMessage({ status: 401 }), /로그인/);
  assert.match(supportErrorMessage({ status: 422 }), /확인/);
  assert.match(supportErrorMessage({ status: 404 }), /아직 쓸 수 없어요/);
  assert.match(supportErrorMessage({ status: 429 }), /자주/);
  assert.match(supportErrorMessage({ code: "network_error" }), /연결/);
  assert.match(supportErrorMessage({ status: 500 }), /처리하지 못했어요/);
  assert.equal(supportErrorMessage(null), "");
});

test("한 건 정리: 상태·종류 이름, 답변 유무, 한국 시간 날짜", () => {
  const v = ticketView({ id: "t1", kind: "report", title: "제목", body: "내용", status: "done", answer: " 확인했어요 ", answered_at: "2026-11-04T16:00:00Z", created_at: "2026-11-03T20:00:00Z" });
  assert.equal(v.kindLabel, "신고");
  assert.equal(v.statusLabel, "답변 완료");
  assert.equal(v.answer, "확인했어요");
  assert.equal(v.answered, true);
  assert.equal(v.answeredOn, "11월 5일"); // UTC 16시 = 한국 다음날 새벽 1시
  assert.equal(v.sentOn, "11월 4일"); // UTC 20시 = 한국 다음날 새벽 5시
  const none = ticketView({ id: 7, status: "new", answer: null });
  assert.equal(none.answered, false);
  assert.equal(none.statusLabel, "접수됨");
  assert.equal(ticketView({ status: "알수없음" }).statusLabel, "접수됨");
  assert.equal(dateText("이상한 값"), "");
});

test("답변 알림: 고객센터 분류가 있고 누르면 내 문의 탭으로 간다", () => {
  assert.equal(KIND_META.support.label, "고객센터");
  assert.equal(routeFor({ kind: "support", event: "ticket_answered" }), "/support?tab=mine");
});
