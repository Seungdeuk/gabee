// 채팅방 공유 카드 보내기(앱): "+" 메뉴 연결, 공유 시트 항목 구성, 확인창 문구, 전송 API 경로·본문·429, 오류 문구, 소스 구조: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import { PLUS_MENU_ITEMS, PLUS_SOON_NOTICE, isPlusFile, isPlusPhoto, isPlusShare, plusShareKind } from "../src/features/family-chat/fileUtils.js";
import {
  SHARE_MONTHS_SHOWN,
  SHARE_NOTICE,
  SHEET_HANDOFF_MS,
  buildShareEventItems,
  recentShareMonths,
  scheduleAfterSheetClose,
  shareConfirmCopy,
  shareSendErrorMessage,
  shareSheetCopy,
} from "../src/features/family-chat/shareUtils.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const read = (rel) => readFileSync(new URL(`../src/${rel}`, import.meta.url), "utf8");
const json = (status, body, headers = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

// ---------------------------------------------------------------------------------------------
// "+" 메뉴

test("+ 메뉴: 라벨·순서는 그대로, 일정·정산만 공유 항목(isPlusShare)이고 안부는 계속 준비 중", () => {
  assert.deepEqual(PLUS_MENU_ITEMS.map((i) => i.label), ["사진", "파일", "일정", "정산", "안부"]);
  assert.deepEqual(PLUS_MENU_ITEMS.map((i) => i.key), ["photo", "file", "schedule", "settle", "safety"]);
  assert.equal(PLUS_SOON_NOTICE, "준비 중이에요");
  assert.equal(isPlusShare("schedule"), true);
  assert.equal(isPlusShare("settle"), true);
  assert.equal(isPlusShare("safety"), false);
  assert.equal(isPlusShare("photo"), false);
  assert.equal(isPlusPhoto("schedule"), false);
  assert.equal(isPlusFile("settle"), false);
  assert.equal(plusShareKind("schedule"), "event");
  assert.equal(plusShareKind("settle"), "settlement");
  assert.equal(plusShareKind("safety"), null);
});

test("Composer: onShare 가 있으면 일정·정산은 공유로 가고, 없거나 안부면 '준비 중' 안내다", () => {
  const composer = read("features/family-chat/components/Composer.js");
  assert.match(composer, /isPlusShare/);
  assert.match(composer, /else if \(onShare && isPlusShare\(key\)\) \{/);
  assert.match(composer, /else setSoon\(true\)/); // 안부(와 onShare 가 없는 경우)는 그대로 준비 중
  assert.match(composer, /shareBusy/); // 공유를 보내는 동안 + 버튼이 진행 표시
});

// ---------------------------------------------------------------------------------------------
// 시트 항목

const ev = (over) => ({ id: "e1", title: "치과", kind: 1, start_date: "2026-11-12", start_time: "15:00", checked: false, ...over });

test("buildShareEventItems: 오늘 이후(오늘 포함)만, 날짜·시간 오름차순(시간 없는 것이 먼저), 지난 일정·날짜 없는 것·끝낸 할 일 제외", () => {
  const events = [
    ev({ id: "late", title: "늦은", start_date: "2026-11-20", start_time: null }),
    ev({ id: "past", title: "지난", start_date: "2026-11-09" }),
    ev({ id: "today-pm", title: "오늘 오후", start_date: "2026-11-10", start_time: "15:00" }),
    ev({ id: "today-am", title: "오늘 오전", start_date: "2026-11-10", start_time: "09:00" }),
    ev({ id: "nodate", title: "날짜 없음", start_date: null }),
    ev({ id: "done", title: "끝낸 할 일", kind: 2, checked: true, start_date: "2026-11-11" }),
    ev({ id: "todo", title: "안 끝낸 할 일", kind: 2, checked: false, start_date: "2026-11-11", start_time: null }),
    ev({ id: "weird", title: "모르는 종류", kind: 9, start_date: "2026-11-11" }),
    null,
  ];
  const items = buildShareEventItems(events, "2026-11-10");
  assert.deepEqual(items.map((i) => i.ref), ["today-am", "today-pm", "todo", "late"]);
  assert.deepEqual(items[0], { key: "e:today-am", ref: "today-am", title: "오늘 오전", line: "11월 10일 (화) · 오전 9:00", badge: "약속" });
  assert.equal(items[2].badge, "할 일");
  assert.equal(items[2].line, "11월 11일 (수) · 종일");
});

test("buildShareEventItems: 목록이 아니거나 비어 있어도 빈 배열", () => {
  assert.deepEqual(buildShareEventItems(null, "2026-11-10"), []);
  assert.deepEqual(buildShareEventItems([], "2026-11-10"), []);
});

test("recentShareMonths: 이번 달부터 거슬러 SHARE_MONTHS_SHOWN 개월(해가 바뀌어도), 월 id 는 YYYY-MM", () => {
  const months = recentShareMonths(new Date(2026, 1, 15)); // 2026-02
  assert.equal(months.length, SHARE_MONTHS_SHOWN);
  assert.equal(SHARE_MONTHS_SHOWN, 6);
  assert.deepEqual(months.map((m) => m.ref), ["2026-02", "2026-01", "2025-12", "2025-11", "2025-10", "2025-09"]);
  assert.deepEqual(months[0], { key: "m:2026-02", ref: "2026-02", title: "2026년 2월", line: "", badge: "정산" });
  assert.equal(recentShareMonths(new Date(2026, 10, 10), 2).length, 2);
});

test("shareSheetCopy: 종류마다 시트 제목·빈 상태·안내 문구가 있다", () => {
  assert.equal(shareSheetCopy("event").title, "공유할 일정 고르기");
  assert.match(shareSheetCopy("event").empty, /오늘 이후/);
  assert.equal(shareSheetCopy("settlement").title, "공유할 정산 달 고르기");
  assert.match(shareSheetCopy("settlement").hint, /정산 내역이 있는 달/);
  assert.equal(shareSheetCopy(null).title, "");
});

// ---------------------------------------------------------------------------------------------
// 확인창

test("고지 문구: 일정·정산 문구가 확정 문장 그대로다(가족방·1:1 방 같음)", () => {
  assert.equal(SHARE_NOTICE.event, "이 일정이 이 채팅방 사람들에게 보여요.");
  assert.equal(SHARE_NOTICE.settlement, "정산 금액이 이 채팅방 사람들에게 보이고, @가비·AI 도우미가 답변에 쓸 수 있어요.");
});

test("shareConfirmCopy: 일정은 제목·날짜와 고지, 정산은 월만 보이고(금액 없음) 고지를 붙인다", () => {
  const ev1 = buildShareEventItems([ev({ id: "x", title: "치과", start_date: "2026-11-12" })], "2026-11-10")[0];
  const e = shareConfirmCopy("event", ev1);
  assert.equal(e.title, "이 일정을 공유할까요?");
  assert.equal(e.message, `치과\n11월 12일 (목) · 오후 3:00\n\n${SHARE_NOTICE.event}`);
  assert.equal(e.confirmLabel, "공유하기");
  const s = shareConfirmCopy("settlement", recentShareMonths(new Date(2026, 10, 10))[0]);
  assert.equal(s.title, "2026년 11월 정산을 공유할까요?");
  assert.equal(s.message, SHARE_NOTICE.settlement);
  assert.doesNotMatch(s.message, /\d+원/); // 금액은 앱이 계산하지 않고 확인창에도 없다
  assert.equal(shareConfirmCopy("event", null).title, "이 일정을 공유할까요?"); // 항목이 없어도 깨지지 않는다
});

test("ConfirmDialog: tone prop(기본 danger, default 면 꿀색 확인 버튼)이 있고 다른 화면은 그대로 빨강이다", () => {
  const dialog = read("shared/components/ConfirmDialog.js");
  assert.match(dialog, /tone = "danger"/);
  assert.match(dialog, /tone === "default"/);
  assert.match(dialog, /backgroundColor: colors\.accent/); // 기본 톤 확인 버튼
  assert.match(dialog, /danger: \{ backgroundColor: colors\.danger \}/); // 기존 빨강은 그대로
});

// ---------------------------------------------------------------------------------------------
// 전송 API

test("API sendShare: POST /family-chat/shares, 본문은 kind·ref·room_id 만(payload 등 없음), 201 MessageOut 반환", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method, body: JSON.parse(init.body) });
    return json(201, { id: 5, text: "일정을 공유했어요", share: { kind: "event", payload: {} } });
  };
  const api = await import("../src/features/family-chat/api.js");
  const saved = await api.sendShare({ kind: "event", ref: "ev-1", roomId: "r1" });
  assert.equal(saved.id, 5);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].url, "http://api.test/family-chat/shares");
  assert.deepEqual(calls[0].body, { kind: "event", ref: "ev-1", room_id: "r1" });
});

test("API sendShare: 가족 전체방(roomId 없음)이면 room_id 를 보내지 않는다, 정산은 ref 가 YYYY-MM", async () => {
  const bodies = [];
  globalThis.fetch = async (_url, init = {}) => {
    bodies.push(JSON.parse(init.body));
    return json(201, { id: 6, text: "정산을 공유했어요", share: { kind: "settlement", payload: {} } });
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.sendShare({ kind: "settlement", ref: "2026-11", roomId: null });
  await api.sendShare({ kind: "settlement", ref: "2026-10" });
  assert.deepEqual(bodies[0], { kind: "settlement", ref: "2026-11" });
  assert.deepEqual(bodies[1], { kind: "settlement", ref: "2026-10" });
  assert.equal("room_id" in bodies[0], false);
});

test("API sendShare: 429 는 Retry-After 가 ApiError.retryAfter 로 남고, 오류 문구에 대기 시간이 붙는다", async () => {
  globalThis.fetch = async () => json(429, { code: "too_many_shares", message: "m" }, { "Retry-After": "30" });
  const api = await import("../src/features/family-chat/api.js");
  let caught = null;
  await api.sendShare({ kind: "event", ref: "e" }).catch((e) => {
    caught = e;
  });
  assert.equal(caught.status, 429);
  assert.equal(caught.code, "too_many_shares");
  assert.equal(caught.retryAfter, 30);
  assert.match(shareSendErrorMessage(caught), /30초 뒤에 다시 시도할 수 있어요/);
});

// ---------------------------------------------------------------------------------------------
// 오류 문구

test("shareSendErrorMessage: 404·invalid_month·share_too_large·409·429·503·네트워크·기본 문구가 모두 다르다", () => {
  const msgs = {
    notFound: shareSendErrorMessage({ status: 404, code: "not_found" }),
    month: shareSendErrorMessage({ status: 400, code: "invalid_month" }),
    tooLarge: shareSendErrorMessage({ status: 400, code: "share_too_large" }),
    peerLeft: shareSendErrorMessage({ status: 409, code: "peer_left_room" }),
    many: shareSendErrorMessage({ status: 429, code: "too_many_shares", retryAfter: 0 }),
    unavailable: shareSendErrorMessage({ status: 503, code: "share_unavailable" }),
    schema: shareSendErrorMessage({ status: 503, code: "schema_not_ready" }),
    network: shareSendErrorMessage({ status: 0, code: "network_error" }),
    other: shareSendErrorMessage({ status: 500, code: "boom" }),
  };
  assert.match(msgs.notFound, /찾지 못했어요/);
  assert.match(msgs.month, /달이 올바르지 않아요/);
  assert.match(msgs.tooLarge, /너무 길어서/);
  assert.equal(msgs.peerLeft, "상대방이 나가서 메시지를 보낼 수 없어요");
  assert.match(msgs.many, /너무 자주/);
  assert.doesNotMatch(msgs.many, /뒤에 다시 시도/); // retryAfter 가 없으면 대기 시간은 붙이지 않는다
  assert.match(msgs.unavailable, /지금은 공유할 수 없어요/);
  assert.equal(msgs.schema, msgs.unavailable);
  assert.match(msgs.network, /인터넷 연결/);
  assert.match(msgs.other, /공유하지 못했어요/);
  assert.equal(new Set([msgs.notFound, msgs.month, msgs.tooLarge, msgs.peerLeft, msgs.many, msgs.unavailable, msgs.network, msgs.other]).size, 8);
  assert.match(shareSendErrorMessage(null), /공유하지 못했어요/);
  assert.match(shareSendErrorMessage({ status: 429, retryAfter: 90 }), /2분 뒤에 다시 시도할 수 있어요/);
});

test("오류 문구에는 카드 내용(제목·금액)이 들어가지 않는다", () => {
  const text = shareSendErrorMessage({ status: 404, message: "치과 12,000원" });
  assert.doesNotMatch(text, /치과|12,000/);
});

// ---------------------------------------------------------------------------------------------
// 소스 구조(렌더 환경이 없어 정규식으로 검사)

test("useChatMessages: sendShare 는 사진·파일과 같은 방식(중복 누름 락, 라이브 복귀, 서버 메시지 병합, 오류는 photoError)이고 반환에 shareBusy 가 있다", () => {
  const hook = read("features/family-chat/useChatMessages.js");
  assert.match(hook, /sendShare as postShare/);
  assert.match(hook, /const shareLock = useRef\(false\)/);
  assert.match(hook, /const sendShare = useCallback\(/);
  assert.match(hook, /async \(\{ kind, ref: cardRef \}\)/); // 바깥 const ref(메시지 목록 ref)를 가리지 않는다
  assert.match(hook, /postShare\(\{ kind, ref: cardRef, roomId: roomRef\.current \}\)/);
  assert.match(hook, /setPhotoError\(shareSendErrorMessage\(e\)\)/);
  assert.match(hook, /sendShare, shareBusy/);
});

test("ChatRoomScreen·useChatShare: 시트·확인창을 훅이 맡고 화면은 연결만 한다, 전송 뒤 맨 아래로 스크롤한다", () => {
  const screen = read("features/family-chat/screens/ChatRoomScreen.js");
  assert.match(screen, /import useChatShare from "\.\.\/useChatShare"/);
  assert.match(screen, /onShare=\{share\.open\}/);
  assert.match(screen, /<ShareSheet /);
  assert.match(screen, /<ConfirmDialog /);
  assert.match(screen, /tone="default"/);
  const hook = read("features/family-chat/useChatShare.js");
  assert.match(hook, /listScheduleEvents/);
  assert.match(hook, /await send\(card\)/); // 전송은 useChatMessages.sendShare 를 받아 쓴다
  assert.match(hook, /onSent\?\.\(\)/);
  assert.match(hook, /confirming\.current/); // 확인 중복 누름 방지
  assert.match(hook, /export default function useChatShare/);
  assert.doesNotMatch(hook, /fetch\(/);
});

test("ShareSheet: theme 토큰만, 로딩·빈 상태·오류(다시 시도)·항목 선택을 처리한다", () => {
  const sheet = read("features/family-chat/components/ShareSheet.js");
  assert.doesNotMatch(sheet, /#[0-9a-fA-F]{3,8}\b/);
  assert.match(sheet, /from "@\/theme"/);
  assert.match(sheet, /ActivityIndicator/);
  assert.match(sheet, /다시 시도/);
  assert.match(sheet, /onPick\(item\)/);
  assert.doesNotMatch(sheet, /fetch\(|apiFetch/);
});

// ---------------------------------------------------------------------------------------------
// 창(Modal) 넘기기: 시트가 닫힌 뒤에 다음 창을 연다(겹쳐 뜨면 iOS 에서 열리지 않는 경우가 있다)

test("SHEET_HANDOFF_MS: ai-assistant ChatInput 선례와 같은 500ms", () => {
  assert.equal(SHEET_HANDOFF_MS, 500);
});

test("scheduleAfterSheetClose: 상호작용이 끝나고 SHEET_HANDOFF_MS 가 지난 뒤에야 한 번 실행한다", () => {
  const pending = [];
  const timers = [];
  let ran = 0;
  scheduleAfterSheetClose(() => (ran += 1), {
    runAfterInteractions: (cb) => pending.push(cb),
    setTimer: (cb, ms) => timers.push({ cb, ms }) && timers.length,
    clearTimer: () => {},
  });
  assert.equal(ran, 0);
  assert.equal(timers.length, 0); // 상호작용(닫는 애니메이션)이 끝나기 전에는 타이머도 없다
  pending[0]();
  assert.equal(ran, 0);
  assert.equal(timers[0].ms, SHEET_HANDOFF_MS);
  timers[0].cb();
  assert.equal(ran, 1);
});

test("scheduleAfterSheetClose: 취소하면(상호작용 전·타이머 중 모두) 실행하지 않는다", () => {
  const pending = [];
  const timers = [];
  const cleared = [];
  const deps = { runAfterInteractions: (cb) => pending.push(cb), setTimer: (cb) => timers.push(cb) && timers.length, clearTimer: (id) => cleared.push(id) };
  let ran = 0;
  const cancelEarly = scheduleAfterSheetClose(() => (ran += 1), deps);
  cancelEarly();
  pending[0](); // 취소했는데 상호작용이 끝나도 타이머를 만들지 않는다
  assert.equal(timers.length, 0);
  const cancelLate = scheduleAfterSheetClose(() => (ran += 1), deps);
  pending[1]();
  cancelLate();
  assert.deepEqual(cleared, [1]);
  assert.equal(ran, 0);
});

test("scheduleAfterSheetClose: 기본 값(즉시 상호작용 완료)에서도 지연 뒤 실행되고 취소할 수 있다", async () => {
  let ran = 0;
  scheduleAfterSheetClose(() => (ran += 1), { delay: 5 });
  const cancel = scheduleAfterSheetClose(() => (ran += 10), { delay: 5 });
  cancel();
  await new Promise((r) => setTimeout(r, 40));
  assert.equal(ran, 1);
});

test("Composer: '+' 시트를 닫은 뒤 공유 시트를 연다(지연·언마운트 정리)", () => {
  const composer = read("features/family-chat/components/Composer.js");
  assert.match(composer, /InteractionManager/);
  assert.match(composer, /scheduleAfterSheetClose\(\(\) => onShare\(plusShareKind\(key\)\)/);
  assert.match(composer, /setSheetOpen\(false\);\s*\n\s*if \(isPlusPhoto/); // 시트는 먼저 닫는다
  assert.match(composer, /handoff\.current\?\.\(\)/); // 언마운트·재선택 때 예약을 취소한다
});

test("useChatShare: 항목을 고르면 시트를 닫고 닫힌 뒤 확인창을, 취소하면 확인창을 닫고 닫힌 뒤 시트를 다시 연다(동시에 두 창을 띄우지 않는다)", () => {
  const hook = read("features/family-chat/useChatShare.js");
  assert.match(hook, /InteractionManager/);
  assert.match(hook, /scheduleAfterSheetClose/);
  assert.match(hook, /confirmVisible/);
  assert.match(hook, /sheetOpen: false/); // 닫아도 kind·items 는 남겨 닫히는 동안 제목이 비지 않는다
  assert.doesNotMatch(hook, /setState\(IDLE\)/); // 닫을 때 내용을 비우지 않는다
  assert.match(hook, /confirmCopy: pending && state\.kind \? shareConfirmCopy/); // 확인창 문구는 열림 여부와 무관하게 마지막 항목을 유지한다
  const screen = read("features/family-chat/screens/ChatRoomScreen.js");
  assert.match(screen, /visible=\{share\.confirmVisible\}/);
});
