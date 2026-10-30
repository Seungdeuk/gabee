// 채팅 할 일 후보 → 함께하기 변환, 서랍 "가족 할 일" 내역, API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  BRIEF_LIMIT,
  MAX_RECIPIENTS,
  DAY_CHIPS,
  briefWhen,
  buildBrief,
  candidateToRequestBody,
  cleanTitle,
  dateKey,
  dayFromChip,
  formatDayInput,
  hasCandidateDay,
  isDay,
  requestErrorText,
  sendErrorMessage,
} from "../src/features/family-chat/togetherUtils.js";
import { buildDrawerSections, resolveRowAction } from "../src/features/family-chat/mediaUtils.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const group = {
  my_id: "me",
  members: [
    { id: "me", name: "엄마" },
    { id: "dad", name: "아빠", display_name: "우리 아빠" },
    { id: "kid", name: "민수" },
    { id: "kid2", name: "민수" },
  ],
};

test("dayFromChip: 기기 시간대의 오늘에서 며칠 뒤, 월말·연말을 넘기고 모르는 칩은 null", () => {
  const now = new Date(2026, 9, 31, 22, 30);
  assert.equal(dayFromChip("today", now), "2026-10-31");
  assert.equal(dayFromChip("tomorrow", now), "2026-11-01");
  assert.equal(dayFromChip("tomorrow", new Date(2026, 11, 31)), "2027-01-01"); // 연말을 넘긴다
  assert.equal(dayFromChip("none", now), null);
  assert.equal(dayFromChip(null, now), null);
  assert.deepEqual(DAY_CHIPS.map((c) => c.key), ["today", "tomorrow", "custom"]);
  assert.deepEqual(DAY_CHIPS.map((c) => c.label), ["오늘", "내일", "직접 입력"]);
  // 직접 입력: 실제 있는 날짜이고 오늘 이후일 때만
  assert.equal(dayFromChip("custom", now, "2026-11-05"), "2026-11-05");
  assert.equal(dayFromChip("custom", now, "2026-10-31"), "2026-10-31"); // 오늘은 괜찮다
  assert.equal(dayFromChip("custom", now, "2026-10-30"), null); // 지난 날짜
  assert.equal(dayFromChip("custom", now, "2026-02-30"), null); // 없는 날짜
  assert.equal(dayFromChip("custom", now, "2026-11-0"), null); // 덜 적음
  assert.equal(dayFromChip("custom", now, null), null);
  assert.equal(dateKey(new Date(2026, 0, 5)), "2026-01-05");
});

test("formatDayInput: 숫자만 남기고 YYYY-MM-DD 로 하이픈을 붙인다", () => {
  assert.equal(formatDayInput("2026"), "2026");
  assert.equal(formatDayInput("202611"), "2026-11");
  assert.equal(formatDayInput("20261105"), "2026-11-05");
  assert.equal(formatDayInput("2026-11-05"), "2026-11-05");
  assert.equal(formatDayInput("2026/11/05 abc 99"), "2026-11-05"); // 8자리까지만
  assert.equal(formatDayInput(null), "");
  assert.equal(requestErrorText("bad_date"), "날짜를 정확히 적어 주세요(예: 2026-11-05, 오늘 이후)");
});

test("isDay·hasCandidateDay: 실제 있는 날짜만", () => {
  assert.equal(isDay("2026-11-02"), true);
  assert.equal(isDay("2026-02-30"), false);
  assert.equal(isDay("내일"), false);
  assert.equal(isDay(null), false);
  assert.equal(hasCandidateDay({ due: "2099-11-02" }), true);
  assert.equal(hasCandidateDay({ due: "다음주" }), false);
  assert.equal(hasCandidateDay(null), false);
});

test("cleanTitle: 연속 공백을 하나로, 120자로 자른다", () => {
  assert.equal(cleanTitle("  장보기   가기 "), "장보기 가기");
  assert.equal(cleanTitle("가".repeat(130)).length, 120);
  assert.equal(cleanTitle(null), "");
});

test("candidateToRequestBody: 날짜는 후보 기한 우선·없으면 고른 날짜, 받는 사람은 담당자 한 명 아니면 나를 뺀 모두", () => {
  assert.deepEqual(candidateToRequestBody({ title: " 김장 도와드리기 ", due: "2026-11-02" }, group, "2026-11-09", "2026-11-01"), { body: { title: "김장 도와드리기", start_date: "2026-11-02", to_ids: ["dad", "kid", "kid2"] } });
  assert.deepEqual(candidateToRequestBody({ title: "장보기" }, group, "2026-11-09", "2026-11-01"), { body: { title: "장보기", start_date: "2026-11-09", to_ids: ["dad", "kid", "kid2"] } });
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "2026-11-02", assignee_name: "아빠" }, group, null, "2026-11-01").body.to_ids, ["dad"]);
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "2026-11-02", assignee_name: "우리 아빠" }, group, null, "2026-11-01").body.to_ids, ["dad"]); // 표시 이름도 정확히 같으면
  assert.equal(candidateToRequestBody({ title: "x", due: "2026-11-02", assignee_name: "민수" }, group, null, "2026-11-01").body.to_ids.length, 3); // 두 사람이면 정하지 않고 모두
  assert.equal(candidateToRequestBody({ title: "x", due: "2026-11-02", assignee_name: "엄" }, group, null, "2026-11-01").body.to_ids.length, 3); // 부분 일치는 안 된다
  assert.equal(candidateToRequestBody({ title: "x", due: "2026-11-02", assignee_name: "엄마" }, group, null, "2026-11-01").body.to_ids.length, 3); // 담당자가 나면 모두에게
});

test("지난 날짜 기한은 쓰지 않고 날짜를 새로 고르게 한다", () => {
  assert.equal(hasCandidateDay({ due: "2026-10-30" }, "2026-11-01"), false);
  assert.equal(hasCandidateDay({ due: "2026-11-01" }, "2026-11-01"), true); // 오늘은 괜찮다
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "2026-10-30" }, group, null, "2026-11-01"), { error: "no_date" });
  assert.equal(candidateToRequestBody({ title: "x", due: "2026-10-30" }, group, "2026-11-02", "2026-11-01").body.start_date, "2026-11-02");
});

test("candidateToRequestBody: 내 id 를 모르면 보내지 않고, 받는 사람은 최대 20명", () => {
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "2026-11-02" }, { members: group.members }, null, "2026-11-01"), { error: "no_recipient" });
  const big = { my_id: "me", members: [{ id: "me", name: "나" }, ...Array.from({ length: 25 }, (_, i) => ({ id: `u${i}`, name: `가${i}` }))] };
  assert.equal(candidateToRequestBody({ title: "x", due: "2026-11-02" }, big, null, "2026-11-01").body.to_ids.length, MAX_RECIPIENTS);
});

test("candidateToRequestBody: 제목·날짜·받는 사람이 없으면 사유를 돌려준다", () => {
  assert.deepEqual(candidateToRequestBody({ title: "  " }, group, "2026-11-09"), { error: "no_title" });
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "내일" }, group, null), { error: "no_date" });
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "내일" }, group, "잘못"), { error: "no_date" });
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "2026-11-02" }, { my_id: "me", members: [{ id: "me", name: "엄마" }] }, null, "2026-11-01"), { error: "no_recipient" });
  assert.deepEqual(candidateToRequestBody({ title: "x", due: "2026-11-02" }, null, null, "2026-11-01"), { error: "no_recipient" });
  assert.equal(requestErrorText("no_date"), "날짜를 골라 주세요");
  assert.equal(requestErrorText("no_recipient"), "함께할 가족이 아직 없어요");
  assert.equal(requestErrorText("이상한값"), "보내지 못했어요. 다시 시도해 주세요");
});

test("sendErrorMessage: 상태별 문구, 제목 같은 내용은 넣지 않는다", () => {
  assert.equal(sendErrorMessage({ status: 0 }), "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요");
  assert.equal(sendErrorMessage({ status: 429 }), "잠시 후 다시 시도해 주세요");
  assert.equal(sendErrorMessage({ status: 422 }), "보내지 못했어요. 내용을 확인해 주세요");
  assert.equal(sendErrorMessage(null), "보내지 못했어요. 다시 시도해 주세요");
});

const req = (id, over = {}) => ({ id, from_id: "dad", title: `요청 ${id}`, start_date: "2026-11-03", start_time: null, canceled: false, recipients: [{ user_id: "me", status: "waiting" }], ...over });
const ev = (id, over = {}) => ({ id, title: `할 일 ${id}`, kind: 2, start_date: "2026-11-02", start_time: null, checked: false, origin_id: null, ...over });

test("buildBrief: 할 일(안 끝낸 것)과 함께하기(받은 것·보낸 것)를 날짜순으로, 같은 날은 함께하기 먼저", () => {
  const rows = buildBrief({
    events: [ev("e1", { start_date: "2026-11-05" }), ev("e2", { start_date: "2026-11-03", start_time: "15:20:00" }), ev("done", { checked: true })],
    requests: [req("r1"), req("r2", { from_id: "me", start_date: "2026-11-04", recipients: [{ user_id: "dad", status: "accepted" }, { user_id: "kid", status: "waiting" }] })],
    myId: "me",
    today: "2026-11-01",
    nameOf: (id) => (id === "dad" ? "아빠" : undefined),
  });
  assert.deepEqual(rows.map((r) => r.key), ["r:r1", "e:e2", "r:r2", "e:e1"]);
  assert.equal(rows[0].tag, "아빠님이 보냈어요");
  assert.deepEqual(rows[0].route, { pathname: "/schedule/together-receive", params: { id: "r1" } });
  assert.equal(rows[1].tag, "내 할 일");
  assert.equal(rows[1].time, "15:20");
  assert.deepEqual(rows[1].route, { pathname: "/schedule/detail", params: { id: "e2" } });
  assert.equal(rows[2].tag, "1명이 함께해요");
  assert.deepEqual(rows[2].route, { pathname: "/schedule/together-detail", params: { id: "r2" } });
});

test("buildBrief: 거절·취소·날짜 지난 요청, 수락해서 생긴 내 할 일(겹침)은 뺀다", () => {
  const rows = buildBrief({
    events: [ev("fromReq"), ev("old", { start_date: "2026-10-30" }), ev("nodate", { start_date: null })],
    requests: [
      req("declined", { recipients: [{ user_id: "me", status: "declined" }] }),
      req("canceled", { canceled: true }),
      req("past", { start_date: "2026-10-30" }),
      req("acc", { my_event_id: "fromReq", recipients: [{ user_id: "me", status: "accepted" }] }),
      req("waitForOthers", { from_id: "me", recipients: [{ user_id: "dad", status: "waiting" }] }),
    ],
    myId: "me",
    today: "2026-11-01",
  });
  assert.deepEqual(rows.map((r) => r.key).sort(), ["r:acc", "r:waitForOthers"]);
  assert.equal(rows.find((r) => r.id === "acc").tag, "함께해요");
  assert.equal(rows.find((r) => r.id === "waitForOthers").tag, "답을 기다려요");
});

test("buildBrief: 일정(약속)도 보이고 끝낸 것 표시는 할 일에만 적용, 태그는 내 일정", () => {
  const rows = buildBrief({
    events: [ev("appt", { kind: 1, start_date: "2026-11-02" }), ev("apptChecked", { kind: 1, checked: true, start_date: "2026-11-03" }), ev("todoDone", { checked: true })],
    requests: [],
    myId: "me",
    today: "2026-11-01",
  });
  assert.deepEqual(rows.map((r) => r.key), ["e:appt", "e:apptChecked"]); // 일정의 checked 는 '확인함'이라 숨기지 않는다
  assert.equal(rows[0].tag, "내 일정");
  assert.equal(rows[0].type, "event");
  assert.deepEqual(rows[0].route, { pathname: "/schedule/detail", params: { id: "appt" } });
});

test("buildBrief: 보낸 요청에 답이 모두 거절이면 '모두 어려워요', 오늘 날짜는 포함", () => {
  const rows = buildBrief({
    events: [ev("today", { start_date: "2026-11-01" })],
    requests: [req("allNo", { from_id: "me", recipients: [{ user_id: "dad", status: "declined" }, { user_id: "kid", status: "declined" }] })],
    myId: "me",
    today: "2026-11-01",
  });
  assert.equal(rows.find((r) => r.id === "allNo").tag, "모두 어려워요");
  assert.ok(rows.some((r) => r.key === "e:today"));
});

test("buildBrief: 잘못된 입력·개수 제한", () => {
  assert.deepEqual(buildBrief({ events: null, requests: undefined, myId: null, today: "2026-11-01" }), []);
  const many = Array.from({ length: BRIEF_LIMIT + 5 }, (_, i) => ev(`e${i}`, { start_date: "2026-12-01" }));
  assert.equal(buildBrief({ events: many, requests: [], myId: "me", today: "2026-11-01" }).length, BRIEF_LIMIT);
});

test("briefWhen: M월 D일(요일) 시간", () => {
  assert.equal(briefWhen({ date: "2026-11-03", time: null }), "11월 3일(화)");
  assert.equal(briefWhen({ date: "2026-11-03", time: "15:20" }), "11월 3일(화) 15:20");
  assert.equal(briefWhen({ date: "이상한값", time: null }), "");
});

test("API sendTogetherRequest·listScheduleEvents·listTogetherRequests: 일정 계약 경로·본문", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    return json(200, init.method === "POST" ? { id: "r9", title: "t", start_date: "2026-11-03" } : []);
  };
  const api = await import("../src/features/family-chat/api.js");
  const sent = await api.sendTogetherRequest({ title: "김장", start_date: "2026-11-03", to_ids: ["dad"] });
  await api.listScheduleEvents();
  await api.listTogetherRequests();
  assert.equal(sent.id, "r9");
  assert.equal(calls[0].method, "POST");
  assert.match(calls[0].url, /\/schedule\/requests$/);
  assert.deepEqual(JSON.parse(calls[0].body), { title: "김장", start_date: "2026-11-03", to_ids: ["dad"] });
  assert.match(calls[1].url, /\/schedule\/events\?include_past=true$/);
  assert.match(calls[2].url, /\/schedule\/requests$/);
});

test("서랍: 가족 할 일 행은 가족방·1:1 모두 동작 행이고 일정 탭 내역 화면으로 간다", () => {
  for (const direct of [false, true]) {
    const row = buildDrawerSections({ direct, pinsReady: true }).flatMap((s) => s.rows).find((r) => r.key === "familytodos");
    assert.equal(row.state, "open");
    assert.equal(row.title, "가족 할 일");
    assert.equal(row.subtitle, "일정 탭의 일정·할 일과 함께하기");
    assert.deepEqual(resolveRowAction(row), { type: "familytodos" });
  }
});
