// 공동 할 일·가족 연락처 순수 함수와 API 경로·본문을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  applySavedNickname,
  contactErrorMessage,
  contactRows,
  memoLine,
  nicknameMap,
  relationLabel,
  validateNickname,
} from "../src/features/family-chat/contactUtils.js";
import {
  applyPatch,
  assigneeName,
  buildEditPatch,
  candidateToTodoBody,
  chipForDue,
  cleanTitle,
  daysUntil,
  dueFromChip,
  dueLabel,
  mergeDone,
  mergeFetched,
  openPreview,
  removeTodo,
  replaceTodo,
  splitTodos,
  todoErrorMessage,
} from "../src/features/family-chat/todoUtils.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

// api.js 는 가져올 때 서버 주소를 읽으므로 환경변수를 정한 뒤에 가져온다
const { createTodo, deleteTodo, listNicknames, listTodos, setNickname, updateTodo } = await import("../src/features/family-chat/api.js");

const realFetch = globalThis.fetch;
const calls = [];
beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const mockFetch = (res) => {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return typeof res === "function" ? res() : res;
  };
};

const now = new Date(2026, 9, 31, 22, 30); // 2026-10-31 밤: 월말 경계
const todo = (over) => ({ id: "t1", title: "장보기", assignee_id: null, due_date: null, done: false, done_at: null, done_by: null, created_by: "me", source: "manual", created_at: "2026-10-30T01:00:00Z", ...over });

test("dueFromChip: 기기 시간대 날짜, 월말·연말을 넘기고, 기한 없음·모르는 칩은 null", () => {
  assert.equal(dueFromChip("none", now), null);
  assert.equal(dueFromChip("bogus", now), null);
  assert.equal(dueFromChip("today", now), "2026-10-31");
  assert.equal(dueFromChip("tomorrow", now), "2026-11-01");
  assert.equal(dueFromChip("d3", now), "2026-11-03");
  assert.equal(dueFromChip("w1", now), "2026-11-07");
  assert.equal(dueFromChip("tomorrow", new Date(2026, 11, 31, 23, 59)), "2027-01-01");
  assert.equal(dueFromChip("tomorrow", new Date(2028, 1, 28, 9, 0)), "2028-02-29"); // 윤년
});

test("chipForDue: 칩과 같은 날짜면 그 칩, 기한 없음은 none, 그 밖의 날짜는 null", () => {
  assert.equal(chipForDue(null, now), "none");
  assert.equal(chipForDue("2026-11-01", now), "tomorrow");
  assert.equal(chipForDue("2026-11-20", now), null);
});

test("daysUntil·dueLabel: 오늘/내일/M월 D일, 지난 기한은 지남과 overdue", () => {
  assert.equal(daysUntil("2026-11-01", now), 1);
  assert.equal(daysUntil("2026-10-30", now), -1);
  assert.equal(daysUntil("2026-02-31", now), null);
  assert.deepEqual(dueLabel("2026-10-31", now), { text: "오늘", overdue: false });
  assert.deepEqual(dueLabel("2026-11-01", now), { text: "내일", overdue: false });
  assert.deepEqual(dueLabel("2026-11-12", now), { text: "11월 12일", overdue: false });
  assert.deepEqual(dueLabel("2026-10-20", now), { text: "지남 · 10월 20일", overdue: true });
  assert.equal(dueLabel(null, now), null);
  assert.equal(dueLabel("내일까지", now), null);
});

test("assigneeName: id 로 이름을 찾고, 없거나 나간 사람은 빈 문자열", () => {
  const members = [{ id: "a", name: "우리 엄마" }];
  assert.equal(assigneeName(members, "a"), "우리 엄마");
  assert.equal(assigneeName(members, "gone"), "");
  assert.equal(assigneeName(members, null), "");
  assert.equal(assigneeName(null, "a"), "");
});

test("splitTodos: 안 끝난 일은 기한 빠른 순(없는 것은 뒤)·만든 순, 끝난 일은 최근 완료 순", () => {
  const list = [
    todo({ id: "n1", due_date: null, created_at: "2026-10-01T00:00:00Z" }),
    todo({ id: "d2", due_date: "2026-11-05" }),
    todo({ id: "d1", due_date: "2026-11-01" }),
    todo({ id: "n0", due_date: null, created_at: "2026-09-01T00:00:00Z" }),
    todo({ id: "x1", done: true, done_at: "2026-10-20T00:00:00Z" }),
    todo({ id: "x2", done: true, done_at: "2026-10-25T00:00:00Z" }),
  ];
  const { open, done } = splitTodos(list);
  assert.deepEqual(open.map((t) => t.id), ["d1", "d2", "n0", "n1"]);
  assert.deepEqual(done.map((t) => t.id), ["x2", "x1"]);
  assert.deepEqual(splitTodos(null), { open: [], done: [] });
});

test("applyPatch: 완료는 시각·내 id 를 임시로 채우고 되돌리면 비운다, null 로 담당자·기한을 비운다, 원본은 그대로", () => {
  const t = todo({ assignee_id: "a", due_date: "2026-11-01" });
  const doneT = applyPatch(t, { done: true }, "me", now);
  assert.equal(doneT.done, true);
  assert.equal(doneT.done_by, "me");
  assert.equal(doneT.done_at, now.toISOString());
  assert.equal(t.done, false);
  const back = applyPatch(doneT, { done: false }, "me", now);
  assert.deepEqual([back.done, back.done_at, back.done_by], [false, null, null]);
  const cleared = applyPatch(t, { assignee_id: null, due_date: null }, "me");
  assert.deepEqual([cleared.assignee_id, cleared.due_date, cleared.title], [null, null, "장보기"]);
  assert.equal(applyPatch(t, { title: "새 제목" }).title, "새 제목");
});

test("replaceTodo·removeTodo: id 가 같은 항목만 바꾸거나 뺀다", () => {
  const list = [todo({ id: "a" }), todo({ id: "b" })];
  assert.equal(replaceTodo(list, "a", todo({ id: "a", title: "바뀜" }))[0].title, "바뀜");
  assert.equal(replaceTodo(list, "zzz", todo({ id: "zzz" })).length, 2);
  assert.deepEqual(removeTodo(list, "a").map((t) => t.id), ["b"]);
});

test("openPreview: 안 끝난 일 개수와 기한 빠른 앞 두 제목", () => {
  const list = [todo({ id: "a", title: "나중", due_date: "2026-12-01" }), todo({ id: "b", title: "먼저", due_date: "2026-11-01" }), todo({ id: "c", title: "없음" }), todo({ id: "d", title: "끝", done: true })];
  assert.deepEqual(openPreview(list), { count: 3, titles: ["먼저", "나중"] });
  assert.deepEqual(openPreview(null), { count: 0, titles: [] });
});

test("buildEditPatch: 바뀐 항목만, 담당자·기한은 null 로 비우고, 'keep' 은 기한을 건드리지 않는다", () => {
  const t = todo({ assignee_id: "a", due_date: "2026-11-01" });
  assert.deepEqual(buildEditPatch(t, { title: " 장보기 ", assigneeId: "a", dueKey: "tomorrow" }, now), {});
  assert.deepEqual(buildEditPatch(t, { title: "마트", assigneeId: null, dueKey: "none" }, now), { title: "마트", assignee_id: null, due_date: null });
  assert.deepEqual(buildEditPatch(t, { title: "장보기", assigneeId: "b", dueKey: "w1" }, now), { assignee_id: "b", due_date: "2026-11-07" });
  assert.deepEqual(buildEditPatch(todo({ due_date: "2026-12-25" }), { title: "장보기", assigneeId: null, dueKey: "keep" }, now), {});
  assert.deepEqual(buildEditPatch(t, { title: "   ", assigneeId: "a", dueKey: "keep" }, now), {}); // 빈 제목은 보내지 않는다
});

test("candidateToTodoBody: 담당자는 이름·표시 이름과 정확히 같고 한 명일 때만, 기한은 실제 날짜일 때만, source 는 chat", () => {
  const members = [
    { id: "a", name: "엄마", display_name: "우리 엄마" },
    { id: "b", name: "아빠", display_name: null },
    { id: "c", name: "삼촌", display_name: "민수" },
    { id: "d", name: "민수", display_name: null },
  ];
  assert.deepEqual(candidateToTodoBody({ title: " 장보기 ", assignee_name: "아빠", due: "2026-11-02" }, members), { title: "장보기", assignee_id: "b", due_date: "2026-11-02", source: "chat" });
  assert.equal(candidateToTodoBody({ title: "x", assignee_name: "우리 엄마" }, members).assignee_id, "a");
  assert.equal(candidateToTodoBody({ title: "x", assignee_name: "엄" }, members).assignee_id, null); // 부분 일치는 안 된다
  assert.equal(candidateToTodoBody({ title: "x", assignee_name: "민수" }, members).assignee_id, null); // 두 사람이면 정하지 않는다
  assert.equal(candidateToTodoBody({ title: "x", assignee_name: null }, members).assignee_id, null);
  assert.equal(candidateToTodoBody({ title: "x", due: "내일" }, members).due_date, null);
  assert.equal(candidateToTodoBody({ title: "x", due: "2026-02-30" }, members).due_date, null);
  assert.equal(candidateToTodoBody({ title: "   " }, members), null);
  assert.equal(candidateToTodoBody({ title: "가".repeat(200) }, members).title.length, 120);
});

test("todoErrorMessage: 코드별 문장, 모르는 코드는 기본 문장, 제목 같은 내용은 넣지 않는다", () => {
  assert.match(todoErrorMessage({ code: "not_allowed" }), /만든 사람이나 가족 관리자만 지울 수 있어요/);
  assert.match(todoErrorMessage({ code: "invalid_member" }), /담당자/);
  assert.match(todoErrorMessage({ code: "invalid_title" }), /제목/);
  assert.match(todoErrorMessage({ code: "todo_limit" }), /너무 많아요/);
  assert.match(todoErrorMessage({ code: "network_error" }), /서버에 연결하지 못했어요/);
  assert.match(todoErrorMessage({ code: "weird", message: "장보기 실패" }), /잠시 문제가 생겼어요/);
});

test("relationLabel: 정해진 관계는 한글, other 는 직접 적은 관계(없으면 가족), 안 정했으면 빈 문자열", () => {
  assert.equal(relationLabel({ family_relation: "mom" }), "엄마");
  assert.equal(relationLabel({ family_relation: "grandpa" }), "할아버지");
  assert.equal(relationLabel({ family_relation: "other", family_relation_detail: " 이모 " }), "이모");
  assert.equal(relationLabel({ family_relation: "other", family_relation_detail: null }), "가족");
  assert.equal(relationLabel({ family_relation: null }), "");
  assert.equal(relationLabel({ family_relation: "alien" }), "");
});

test("contactRows: 나는 맨 위에 별명·대화 없이, 별명이 있으면 별명이 title 이고 표시 이름이 subtitle, 메모는 한 줄로", () => {
  const members = [
    { id: "dad", name: "아빠", display_name: null, family_relation: "dad", photo_url: null },
    { id: "me", name: "지민", display_name: null, photo_url: "/p" },
    { id: "mom", name: "엄마", display_name: "우리 엄마", family_relation: "mom", photo_url: null },
  ];
  const nicks = nicknameMap([
    { target_user_id: "mom", nickname: "마미", memo: "생일\n3월 2일" },
    { target_user_id: "me", nickname: "나님", memo: "x" },
  ]);
  const rows = contactRows(members, "me", nicks);
  assert.deepEqual(rows.map((r) => r.id), ["me", "dad", "mom"]);
  assert.equal(rows[0].isMe, true);
  assert.equal(rows[0].title, "지민");
  assert.equal(rows[0].nickname, "");
  assert.equal(rows[0].memo, "");
  assert.deepEqual([rows[1].title, rows[1].subtitle, rows[1].relation], ["아빠", "", "아빠"]);
  assert.deepEqual([rows[2].title, rows[2].subtitle, rows[2].memo], ["마미", "우리 엄마", "생일 3월 2일"]);
  assert.deepEqual(contactRows(null, "me"), []);
  assert.equal(memoLine("a\n\nb"), "a b");
});

test("validateNickname·applySavedNickname: 길이 검사, 둘 다 비면 항목 삭제", () => {
  assert.equal(validateNickname("가".repeat(40), "메모"), "");
  assert.match(validateNickname("가".repeat(41), ""), /40자/);
  assert.match(validateNickname("", "가".repeat(1001)), /1000자/);
  assert.equal(validateNickname("", ""), "");
  const map = { a: { nickname: "별", memo: "" } };
  assert.deepEqual(applySavedNickname(map, "b", { nickname: "새", memo: null }), { a: map.a, b: { nickname: "새", memo: "" } });
  assert.deepEqual(applySavedNickname(map, "a", { nickname: null, memo: null }), {});
  assert.match(contactErrorMessage({ code: "invalid_nickname" }), /40자/);
  assert.match(contactErrorMessage({ code: "cannot_nickname_self" }), /자기 자신/);
  assert.match(contactErrorMessage({ code: "network_error" }), /서버에 연결하지 못했어요/);
});

test("listTodos: GET /family-chat/todos 에 status·limit 쿼리, 토큰은 URL 이 아니라 헤더", async () => {
  mockFetch(() => json(200, []));
  await listTodos("done", 50);
  await listTodos();
  await listTodos("weird", 7);
  assert.equal(calls[0].url, "http://api.test/family-chat/todos?status=done&limit=50");
  assert.equal(calls[1].url, "http://api.test/family-chat/todos?status=open&limit=100");
  assert.equal(calls[2].url, "http://api.test/family-chat/todos?status=open&limit=7");
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.headers["X-Gyeot-Token"], "legacy-dev-token");
  assert.ok(!calls[0].url.includes("legacy-dev-token"));
});

test("createTodo: POST 본문 그대로, JSON 헤더", async () => {
  mockFetch(() => json(201, todo({})));
  const body = { title: "장보기", assignee_id: "a", due_date: "2026-11-01", source: "chat" };
  await createTodo(body);
  assert.equal(calls[0].url, "http://api.test/family-chat/todos");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), body);
});

test("updateTodo: PATCH 에 보낸 항목만, null 로 비우기와 done 을 그대로 보낸다", async () => {
  mockFetch(() => json(200, todo({})));
  await updateTodo("t 1", { assignee_id: null, due_date: null, done: false });
  assert.equal(calls[0].url, "http://api.test/family-chat/todos/t%201");
  assert.equal(calls[0].init.method, "PATCH");
  assert.deepEqual(JSON.parse(calls[0].init.body), { assignee_id: null, due_date: null, done: false });
});

test("deleteTodo: DELETE, 204 는 null, 403 은 not_allowed 코드를 가진 오류", async () => {
  mockFetch(() => new Response(null, { status: 204 }));
  assert.equal(await deleteTodo("t1"), null);
  assert.equal(calls[0].init.method, "DELETE");
  assert.equal(calls[0].init.body, undefined);
  mockFetch(() => json(403, { code: "not_allowed", message: "x" }));
  await assert.rejects(deleteTodo("t1"), (e) => e.status === 403 && e.code === "not_allowed");
});

test("listNicknames·setNickname: family-group 계약 경로, 빈 값은 null 로 보내 지운다", async () => {
  mockFetch(() => json(200, []));
  await listNicknames();
  assert.equal(calls[0].url, "http://api.test/family-group/groups/me/nicknames");
  mockFetch(() => json(200, { target_user_id: "u1", nickname: "마미", memo: null }));
  await setNickname("u1", { nickname: " 마미 ", memo: "" });
  assert.equal(calls[1].url, "http://api.test/family-group/groups/me/nicknames/u1");
  assert.equal(calls[1].init.method, "PUT");
  assert.deepEqual(JSON.parse(calls[1].init.body), { nickname: "마미", memo: null });
  await setNickname("u1", { nickname: "", memo: "  " });
  assert.deepEqual(JSON.parse(calls[2].init.body), { nickname: null, memo: null });
});

test("cleanTitle: 연속 공백을 하나로 줄여 서버와 같게 하고, 그래서 안 바꾼 제목은 PATCH 에 안 들어간다", () => {
  assert.equal(cleanTitle("  장보기   마트  "), "장보기 마트");
  const t = todo({ title: "장보기 마트" });
  assert.deepEqual(buildEditPatch(t, { title: "장보기   마트 ", assigneeId: null, dueKey: "keep" }, now), {});
});

test("buildEditPatch: 창을 연 때의 날짜(now)를 쓰면 자정을 넘겨도 '오늘' 칩 기한이 그대로", () => {
  const opened = new Date(2026, 9, 31, 23, 59);
  assert.equal(buildEditPatch(todo({}), { title: "장보기", assigneeId: null, dueKey: "today" }, opened).due_date, "2026-10-31");
});

test("mergeDone: 펼치기 응답과 겹쳐 토글해도 중복 없이 현재 값 우선, 요청 중 바뀐 항목은 건너뜀", () => {
  const a = todo({ id: "a" });
  const aDone = todo({ id: "a", done: true, done_at: "2026-10-31T00:00:00Z" });
  const b = todo({ id: "b" });
  // a 를 완료로 토글(현재 done) 하는 사이 서버 응답에는 a 가 아직 없거나 있다
  assert.deepEqual(mergeDone([aDone, b], [todo({ id: "x", done: true })], new Set(["a"])).map((t) => t.id), ["a", "b", "x"]);
  assert.deepEqual(mergeDone([aDone, b], [todo({ id: "a", done: true }), todo({ id: "x", done: true })], new Set(["a"])).map((t) => t.id), ["a", "b", "x"]);
  // 응답에서 done 이었던 x 를 되돌리는 중(현재 open)이면 끝난 일에 다시 안 넣는다
  const xOpen = todo({ id: "x" });
  const merged = mergeDone([xOpen, b], [todo({ id: "x", done: true }), todo({ id: "y", done: true })], new Set(["x"]));
  assert.deepEqual(merged.map((t) => t.id), ["x", "b", "y"]);
  assert.equal(merged[0].done, false);
  // 요청 중 지운 항목은 되살리지 않는다
  assert.deepEqual(mergeDone([b], [todo({ id: "z", done: true })], new Set(["z"])).map((t) => t.id), ["b"]);
});

test("mergeFetched: 요청 중 바뀐 항목은 현재 값을 지키고, 지운 항목은 되살리지 않고, 중복은 한 번", () => {
  const cur = [todo({ id: "a", title: "화면 값" }), todo({ id: "c" })];
  const fetched = [todo({ id: "a", title: "서버 옛값" }), todo({ id: "b" }), todo({ id: "b" }), todo({ id: "gone" })];
  const out = mergeFetched(cur, fetched, new Set(["a", "gone"]));
  assert.deepEqual(out.map((t) => t.id), ["a", "b"]);
  assert.equal(out[0].title, "화면 값");
  assert.deepEqual(mergeFetched(cur, fetched, new Set()).map((t) => t.id), ["a", "b", "gone"]);
  assert.deepEqual(mergeFetched(cur, [], new Set(["c"])).map((t) => t.id), ["c"]);
});
