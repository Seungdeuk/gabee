// 메시지-일정/할 일 연결 순수 함수·API 경로·서랍 행을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import { linkErrorMessage } from "../src/features/family-chat/chatUtils.js";
import {
  BADGE_LABEL,
  EMPTY_LINKS_TEXT,
  LINKS_LIMIT,
  badgesFor,
  canDeleteLink,
  canReloadLinks,
  cleanTitle,
  deleteFailureEffect,
  filterByKind,
  formatLinkWhen,
  initialLinksState,
  isTempLink,
  linkA11yLabel,
  linkInputFromCandidate,
  linkKey,
  linkSourceId,
  linkSourceLine,
  linksByMessage,
  linksReducer,
  nextLinkPollDelay,
  normalizeLinks,
  optimisticLink,
  runGuarded,
  tryBegin,
} from "../src/features/family-chat/linkUtils.js";
import { pinTapAction } from "../src/features/family-chat/pinUtils.js";

process.env.TZ = "Asia/Seoul";
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
const link = (id, at, extra = {}) => ({
  id,
  room_id: "fam",
  message_id: 10,
  kind: "event",
  target_id: `e-${id}`,
  title: `제목 ${id}`,
  date: "2026-10-28",
  time: "15:00",
  created_by: "me",
  created_by_name: "지민",
  created_at: at,
  message_text: "내일 3시에 병원 가요",
  message_user_name: "엄마",
  ...extra,
});
const me = { id: "me", name: "지민" };
const ids = (items) => items.map((l) => l.id);

test("연결 가능 판정: source_message_ids 의 첫 번째 정수만, 비면 null", () => {
  assert.equal(linkSourceId({ source_message_ids: [7, 9] }), 7);
  assert.equal(linkSourceId({ source_message_ids: [] }), null);
  assert.equal(linkSourceId({}), null);
  assert.equal(linkSourceId({ source_message_ids: [0] }), null);
  assert.equal(linkSourceId({ source_message_ids: ["x"] }), null);
  assert.equal(linkSourceId(null), null);
});

test("후보 → 연결 본문: 일정은 date/time, 할 일은 due, 올바르지 않으면 null, 원본·id 가 없으면 생략", () => {
  const event = { title: "  병원  예약 ", date: "2026-10-28", time: "15:00", place: "서울병원", source_message_ids: [12, 13] };
  assert.deepEqual(linkInputFromCandidate({ kind: "event", targetId: "ev1", candidate: event }), { messageId: 12, kind: "event", targetId: "ev1", title: "병원 예약", date: "2026-10-28", time: "15:00" });
  // 날짜·시간이 없거나 이상하면 null 로 둔다(지어내지 않는다)
  const odd = linkInputFromCandidate({ kind: "event", targetId: "ev1", candidate: { ...event, date: "2026-02-31", time: "25:00" } });
  assert.equal(odd.date, null);
  assert.equal(odd.time, null);
  assert.equal(linkInputFromCandidate({ kind: "event", targetId: "ev1", candidate: { ...event, date: null, time: null } }).date, null);
  const todo = linkInputFromCandidate({ kind: "todo", targetId: 5, candidate: { title: "우유 사기", due: "2026-10-30", time: "09:00", source_message_ids: [3] } });
  assert.deepEqual(todo, { messageId: 3, kind: "todo", targetId: "5", title: "우유 사기", date: "2026-10-30", time: null }); // 할 일은 시간이 없다
  assert.equal(linkInputFromCandidate({ kind: "todo", targetId: "t", candidate: { title: "x", due: "내일", source_message_ids: [3] } }).date, null);
  // 생략: 원본 없음 / 등록 id 없음 / 제목 없음 / 종류 이상
  assert.equal(linkInputFromCandidate({ kind: "event", targetId: "ev1", candidate: { ...event, source_message_ids: [] } }), null);
  assert.equal(linkInputFromCandidate({ kind: "event", targetId: "", candidate: event }), null);
  assert.equal(linkInputFromCandidate({ kind: "event", targetId: undefined, candidate: event }), null);
  assert.equal(linkInputFromCandidate({ kind: "event", targetId: "ev1", candidate: { ...event, title: "   " } }), null);
  assert.equal(linkInputFromCandidate({ kind: "memo", targetId: "ev1", candidate: event }), null);
  assert.equal(linkInputFromCandidate({ kind: "event", targetId: "ev1", candidate: { ...event, title: "가".repeat(200) } }).title.length, 120);
});

test("목록 정리: 이상한 항목 제거·같은 id 한 번·최신순·최대 개수", () => {
  const list = normalizeLinks([link("a", "2026-10-24T01:00:00Z"), link("b", "2026-10-24T03:00:00Z"), link("a", "2026-10-24T02:00:00Z", { title: "새 a" }), { id: "x" }, null, link("c", "2026-10-24T02:30:00Z", { kind: "memo" })]);
  assert.deepEqual(ids(list), ["b", "a"]);
  assert.equal(list[1].title, "새 a");
  const many = Array.from({ length: LINKS_LIMIT + 5 }, (_, i) => link(`l${i}`, new Date(Date.UTC(2026, 9, 1, 0, i)).toISOString(), { target_id: `t${i}` }));
  assert.equal(normalizeLinks(many).length, LINKS_LIMIT);
  assert.deepEqual(normalizeLinks("nope"), []);
});

test("종류 필터: 최신순을 지킨다", () => {
  const list = normalizeLinks([link("a", "2026-10-24T01:00:00Z"), link("b", "2026-10-24T03:00:00Z", { kind: "todo", time: null }), link("c", "2026-10-24T02:00:00Z")]);
  assert.deepEqual(ids(filterByKind(list, "event")), ["c", "a"]);
  assert.deepEqual(ids(filterByKind(list, "todo")), ["b"]);
  assert.deepEqual(ids(filterByKind(list, "all")), ["b", "c", "a"]);
});

test("낙관적 추가: 임시 항목이 맨 앞에 생기고 같은 대상이면 만들지 않는다", () => {
  const input = { messageId: 10, kind: "event", targetId: "e1", title: "병원", date: "2026-10-28", time: "15:00" };
  const base = normalizeLinks([link("a", "2026-10-24T01:00:00Z")]);
  const first = optimisticLink(base, input, me, { text: "내일 3시", user_name: "엄마" }, { nowIso: "2026-10-24T05:00:00Z", tempId: "tmp:1", roomId: null });
  assert.equal(first.added.id, "tmp:1");
  assert.equal(isTempLink(first.added), true);
  assert.equal(first.added.message_text, "내일 3시");
  assert.deepEqual(ids(first.links), ["tmp:1", "a"]);
  assert.equal(canDeleteLink(first.added, "me"), false); // 임시 항목은 아직 못 지운다
  const again = optimisticLink(first.links, input, me, null, { nowIso: "2026-10-24T05:01:00Z", tempId: "tmp:2" });
  assert.equal(again.added, null);
  assert.equal(again.links.length, 2);
});

test("확정·되돌림: 서버 항목이 임시 항목을 바꾸고, 실패하면 그 임시 항목만 빠진다", () => {
  const input = { messageId: 10, kind: "event", targetId: "e1", title: "병원", date: null, time: null };
  let st = linksReducer(initialLinksState, { type: "loaded", seq: 1, items: [link("a", "2026-10-24T01:00:00Z")] });
  const { added } = optimisticLink(st.items, input, me, null, { nowIso: "2026-10-24T05:00:00Z", tempId: "tmp:1" });
  st = linksReducer(st, { type: "add", seq: 2, item: added });
  assert.deepEqual(ids(st.items), ["tmp:1", "a"]);
  const ok = linksReducer(st, { type: "confirmed", seq: 3, tempId: "tmp:1", item: link("L1", "2026-10-24T05:00:01Z", { target_id: "e1" }) });
  assert.deepEqual(ids(ok.items), ["L1", "a"]);
  const failed = linksReducer(st, { type: "revert_add", seq: 3, tempId: "tmp:1" });
  assert.deepEqual(ids(failed.items), ["a"]);
});

test("서버 항목이 이미 같은 대상이면 임시 항목은 목록에서 빠진다(조회가 먼저 온 경우)", () => {
  const input = { messageId: 10, kind: "event", targetId: "e1", title: "병원", date: null, time: null };
  const { added } = optimisticLink([], input, me, null, { nowIso: "2026-10-24T05:00:00Z", tempId: "tmp:1" });
  const merged = normalizeLinks([added, link("L1", "2026-10-24T05:00:01Z", { target_id: "e1" })]);
  assert.deepEqual(ids(merged), ["L1"]);
});

test("겹친 요청: A 등록 대기 중 X 삭제 성공 → A 실패해도 X 는 되살아나지 않는다", () => {
  let st = linksReducer(initialLinksState, { type: "loaded", seq: 1, items: [link("x", "2026-10-24T01:00:00Z"), link("y", "2026-10-24T02:00:00Z", { target_id: "ey" })] });
  const { added } = optimisticLink(st.items, { messageId: 11, kind: "todo", targetId: "t9", title: "A", date: null, time: null }, me, null, { nowIso: "2026-10-24T05:00:00Z", tempId: "tmp:A" });
  st = linksReducer(st, { type: "add", seq: 2, item: added });
  st = linksReducer(st, { type: "remove", seq: 3, linkId: "x" }); // X 삭제(성공해서 되돌리지 않음)
  st = linksReducer(st, { type: "revert_add", seq: 4, tempId: "tmp:A" }); // A 실패
  assert.deepEqual(ids(st.items), ["y"]);
  // 삭제가 실패하면 그 항목만 되살아난다
  const back = linksReducer(st, { type: "revert_remove", seq: 5, item: link("x", "2026-10-24T01:00:00Z") });
  assert.deepEqual(ids(back.items), ["y", "x"]);
});

test("조회 응답: 그 조회를 시작한 뒤에 내가 바꾼 것이 있으면 오래된 응답을 버린다", () => {
  let st = linksReducer(initialLinksState, { type: "loaded", seq: 1, items: [link("a", "2026-10-24T01:00:00Z")] });
  st = linksReducer(st, { type: "remove", seq: 3, linkId: "a" });
  const stale = linksReducer(st, { type: "loaded", seq: 2, items: [link("a", "2026-10-24T01:00:00Z")] }); // seq 2 조회는 삭제(seq 3)보다 먼저 시작
  assert.deepEqual(stale.items, []);
  const fresh = linksReducer(st, { type: "loaded", seq: 4, items: [link("b", "2026-10-24T02:00:00Z")] });
  assert.deepEqual(ids(fresh.items), ["b"]);
});

test("added 가 없어도(이미 같은 대상) 확정은 서버 항목을 넣는다", () => {
  let st = linksReducer(initialLinksState, { type: "loaded", seq: 1, items: [link("a", "2026-10-24T01:00:00Z")] });
  st = linksReducer(st, { type: "confirmed", seq: 2, tempId: "", item: link("b", "2026-10-24T02:00:00Z", { target_id: "eb" }) });
  assert.deepEqual(ids(st.items), ["b", "a"]);
});

test("메시지별 맵과 말풍선 표시: 종류마다 하나, 일정 먼저", () => {
  const list = normalizeLinks([link("a", "2026-10-24T01:00:00Z"), link("b", "2026-10-24T03:00:00Z", { kind: "todo", message_id: 10, target_id: "t1" }), link("c", "2026-10-24T02:00:00Z", { message_id: 20 }), link("d", "2026-10-24T04:00:00Z", { message_id: 10, target_id: "e-other" })]);
  const map = linksByMessage(list);
  assert.deepEqual(ids(map.get(10)), ["d", "b", "a"]);
  assert.deepEqual(ids(map.get(20)), ["c"]);
  assert.equal(map.get(99), undefined);
  assert.deepEqual(badgesFor(map.get(10)), [
    { kind: "event", label: "일정으로 등록됨" },
    { kind: "todo", label: "할 일로 등록됨" },
  ]);
  assert.deepEqual(badgesFor(map.get(20)), [{ kind: "event", label: BADGE_LABEL.event }]);
  assert.deepEqual(badgesFor(undefined), []);
});

test("삭제 권한: 내가 만든 서버 연결만", () => {
  assert.equal(canDeleteLink(link("a", "2026-10-24T01:00:00Z"), "me"), true);
  assert.equal(canDeleteLink(link("a", "2026-10-24T01:00:00Z", { created_by: "dad" }), "me"), false);
  assert.equal(canDeleteLink(link("tmp:1", "2026-10-24T01:00:00Z"), "me"), false);
  assert.equal(canDeleteLink(link("a", "2026-10-24T01:00:00Z"), null), false);
  assert.equal(canDeleteLink(null, "me"), false);
});

test("날짜·시간·원본 줄 표시", () => {
  const now = new Date(2026, 9, 24);
  assert.equal(formatLinkWhen("2026-10-28", "15:00", now), "10월 28일 · 오후 3:00");
  assert.equal(formatLinkWhen("2026-10-28", null, now), "10월 28일");
  assert.equal(formatLinkWhen("2027-01-05", "00:05", now), "2027년 1월 5일 · 오전 12:05");
  assert.equal(formatLinkWhen(null, "09:30", now), "오전 9:30");
  assert.equal(formatLinkWhen(null, null, now), "");
  assert.equal(formatLinkWhen("2026-02-31", "99:99", now), "");
  assert.equal(linkSourceLine(link("a", "x")), "원본: 엄마 · 내일 3시에 병원 가요");
  assert.equal(linkSourceLine(link("a", "x", { message_text: "a\n  b" }), "엄마(별명)"), "원본: 엄마(별명) · a b");
  assert.equal(linkSourceLine(link("a", "x", { message_text: "", message_user_name: "" })), "원본: 가족");
  assert.match(linkA11yLabel(link("a", "x")), /^일정, 제목 a, 10월 28일 · 오후 3:00\. 원본: 엄마/);
  assert.match(linkA11yLabel(link("a", "x")), /누르면 그 메시지로 이동해요$/);
});

test("이동 판단(고정 바와 같은 pinTapAction 을 쓴다): 라이브에서 목록에 있으면 scroll, 없거나 과거 창이면 focus", () => {
  const messages = [{ id: 5 }, { id: "6" }, { id: 7, clientId: "tmp" }];
  assert.equal(pinTapAction({ messages, messageId: 5, focusing: false }), "scroll");
  assert.equal(pinTapAction({ messages, messageId: 6, focusing: false }), "scroll");
  assert.equal(pinTapAction({ messages, messageId: 1, focusing: false }), "focus");
  assert.equal(pinTapAction({ messages, messageId: 7, focusing: false }), "focus"); // 임시 메시지는 목록에 있는 것으로 보지 않는다
  assert.equal(pinTapAction({ messages, messageId: 5, focusing: true }), "focus");
});

test("폴링 간격·키·빈 상태 문구", () => {
  assert.equal(nextLinkPollDelay(0), 30000);
  assert.equal(nextLinkPollDelay(1), 60000);
  assert.equal(nextLinkPollDelay(2), 120000);
  assert.equal(nextLinkPollDelay(9), 120000);
  assert.equal(nextLinkPollDelay(0, false), null); // 1:1 방은 반복 조회를 하지 않는다
  assert.equal(nextLinkPollDelay(3, false), null);
  assert.equal(linkKey({ messageId: "10", kind: "todo", targetId: "t" }), "10:todo:t");
  assert.equal(EMPTY_LINKS_TEXT, "아직 대화에서 등록한 일정·할 일이 없어요");
});

test("제목 120 글자 자르기는 코드포인트 단위라 이모지가 깨지지 않는다", () => {
  const cut = cleanTitle(`${"a".repeat(119)}😀b`);
  assert.equal(Array.from(cut).length, 120);
  assert.ok(cut.endsWith("😀")); // 두 칸짜리 글자가 중간에서 잘리지 않는다
  assert.equal(Array.from(cleanTitle("😀".repeat(200))).length, 120);
  assert.ok(!/[\ud800-\udbff]$/.test(cleanTitle("😀".repeat(200))));
  assert.equal(cleanTitle("  a \n b  "), "a b");
  assert.equal(linkInputFromCandidate({ kind: "event", targetId: "e", candidate: { title: "😀".repeat(200), source_message_ids: [1] } }).title, "😀".repeat(120));
});

test("runGuarded: 던져도 반드시 leave 를 부르고 false 를 돌려주며 자신은 던지지 않는다", async () => {
  let pending = 1;
  let errors = 0;
  assert.equal(await runGuarded({ work: async () => true, leave: () => (pending -= 1) }), true);
  assert.equal(pending, 0);
  pending = 1;
  const boom = async () => {
    throw new Error("x");
  };
  assert.equal(await runGuarded({ work: boom, onError: () => (errors += 1), leave: () => (pending -= 1) }), false);
  assert.deepEqual([pending, errors], [0, 1]);
  pending = 1;
  const syncBoom = () => {
    throw new Error("sync");
  };
  const result = await runGuarded({
    work: syncBoom,
    onError: syncBoom,
    leave: () => {
      pending -= 1;
      syncBoom();
    },
  });
  assert.equal(result, false); // 동기 예외·정리 중 예외도 삼킨다
  assert.equal(pending, 0);
});

test("조회·연타·삭제 실패·한 번만 열기 판단", () => {
  assert.equal(canReloadLinks(0), true);
  assert.equal(canReloadLinks(1), false); // 요청 중에는 조회를 건너뛴다
  const busy = new Set();
  assert.equal(tryBegin(busy, "10:event:e1"), true);
  assert.equal(tryBegin(busy, "10:event:e1"), false); // 같은 키 연타는 한 번만
  assert.equal(tryBegin(busy, "10:todo:e1"), true);
  busy.delete("10:event:e1");
  assert.equal(tryBegin(busy, "10:event:e1"), true);
  assert.equal(deleteFailureEffect({ status: 404 }), "keep");
  assert.equal(deleteFailureEffect({ status: 403 }), "revert");
  assert.equal(deleteFailureEffect({ status: 0 }), "revert");
  assert.equal(deleteFailureEffect(null), "revert");
});

test("오류 문구", () => {
  assert.equal(linkErrorMessage({ status: 400, code: "invalid_message" }), "이 메시지는 연결할 수 없어요");
  assert.equal(linkErrorMessage({ status: 400, code: "invalid_target" }), "연결할 일정·할 일을 찾을 수 없어요");
  assert.equal(linkErrorMessage({ status: 400, code: "too_many_links" }), "연결이 너무 많아요");
  assert.equal(linkErrorMessage({ status: 403, code: "forbidden" }, "delete"), "만든 사람만 지울 수 있어요");
  assert.equal(linkErrorMessage({ status: 403 }, "delete"), "만든 사람만 지울 수 있어요");
  assert.equal(linkErrorMessage({ status: 404 }, "delete"), "이미 지워진 연결이에요");
  assert.equal(linkErrorMessage({ status: 404 }), "대화방을 찾을 수 없거나 권한이 없어요");
  assert.equal(linkErrorMessage({ status: 429 }), "너무 자주 했어요. 잠시 뒤에 다시 해 주세요");
  assert.equal(linkErrorMessage({ status: 0, code: "network_error" }), "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요");
  assert.equal(linkErrorMessage(null), "잠시 문제가 생겼어요. 다시 시도해 주세요");
});

test("API listLinks·createLink·deleteLink: 경로·메서드·본문·쿼리", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    if (init.method === "DELETE") return new Response(null, { status: 204 });
    return json(init.method === "POST" ? 201 : 200, init.method === "POST" ? link("L1", "2026-10-24T05:00:00Z") : { items: [] });
  };
  const api = await import("../src/features/family-chat/api.js");

  await api.listLinks();
  await api.listLinks({ roomId: "r 1", kind: "todo", limit: 100 });
  await api.listLinks({ kind: "memo", limit: 999 });
  await api.listLinks({ limit: 0 });
  const made = await api.createLink({ messageId: "10", kind: "event", targetId: "e1", title: "병원", date: "2026-10-28", time: "15:00" });
  await api.createLink({ roomId: "r1", messageId: 11, kind: "todo", targetId: 5, title: "우유", date: null, time: null });
  const removed = await api.deleteLink({ linkId: "L 1" });
  await api.deleteLink({ roomId: "r1", linkId: "L2" });

  assert.equal(calls[0].method, "GET");
  assert.match(calls[0].url, /\/family-chat\/links\?limit=50$/);
  assert.match(calls[1].url, /\/family-chat\/links\?room_id=r%201&kind=todo&limit=100$/);
  assert.match(calls[2].url, /\/family-chat\/links\?limit=100$/); // 이상한 종류는 보내지 않고 limit 은 100 으로 줄인다
  assert.match(calls[3].url, /\/family-chat\/links\?limit=50$/);
  assert.equal(calls[4].method, "POST");
  assert.match(calls[4].url, /\/family-chat\/links$/);
  assert.deepEqual(JSON.parse(calls[4].body), { message_id: 10, kind: "event", target_id: "e1", title: "병원", date: "2026-10-28", time: "15:00" }); // 가족 전체방은 room_id 없음
  assert.deepEqual(JSON.parse(calls[5].body), { room_id: "r1", message_id: 11, kind: "todo", target_id: "5", title: "우유" }); // null 날짜·시간은 보내지 않는다
  assert.equal(made.id, "L1");
  assert.equal(calls[6].method, "DELETE");
  assert.match(calls[6].url, /\/family-chat\/links\/L%201$/);
  assert.match(calls[7].url, /\/family-chat\/links\/L2\?room_id=r1$/);
  assert.equal(removed, null);
});

test("API createLink·deleteLink: 400·403 은 ApiError 로 올라와 문구가 된다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  globalThis.fetch = async () => json(400, { code: "invalid_message", message: "m" });
  await assert.rejects(
    () => api.createLink({ messageId: 1, kind: "event", targetId: "e", title: "t" }),
    (e) => {
      assert.equal(e.status, 400);
      assert.equal(linkErrorMessage(e), "이 메시지는 연결할 수 없어요");
      return true;
    },
  );
  globalThis.fetch = async () => json(403, { code: "forbidden", message: "m" });
  await assert.rejects(
    () => api.deleteLink({ linkId: "L1" }),
    (e) => {
      assert.equal(e.status, 403);
      assert.equal(linkErrorMessage(e, "delete"), "만든 사람만 지울 수 있어요");
      return true;
    },
  );
});

test("소스 검사: AiPanel 은 등록 성공 뒤에만 onLinked 를 부르고, 실패 분기에서는 부르지 않는다", () => {
  const src = readFileSync(new URL("../src/features/family-chat/components/AiPanel.js", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  const slice = (from, to) => src.slice(src.indexOf(from), src.indexOf(to, src.indexOf(from)));
  const event = slice("const created = await registerScheduleCandidate", "} catch (e) {");
  assert.match(event, /setRegistered\(.*"ok".*\)[\s\S]*notifyLinked\(\{ kind: "event"/);
  const todo = slice("await sendTogetherRequest", "} catch (e) {");
  assert.match(todo, /setTodoRegistered\(.*"ok".*\)/);
  assert.ok(!todo.includes("notifyLinked("), "함께하기 요청 id 는 서버 연결이 받지 않아 연결을 만들지 않는다");
  for (const part of src.split("} catch (e) {").slice(1)) assert.ok(!part.slice(0, 200).includes("notifyLinked("), "실패 분기에서 연결을 부르면 안 된다");
  assert.match(src, /const notifyLinked = [\s\S]*?try \{[\s\S]*?onLinked\?\.\(link\)[\s\S]*?\} catch/); // 연결 오류는 삼킨다
});
