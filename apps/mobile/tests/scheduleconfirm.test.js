// 채팅의 일정 확인 카드(가족 공유 등록·수정·삭제): 서버 응답 변환, 버튼, 결과 문구, 확인 요청 모양을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  CANCELLED_TEXT,
  CARD_PENDING,
  cardButtons,
  confirmResultText,
  mapChatCards,
  mapConfirmCards,
  mapProposals,
} from "../src/features/ai-assistant/scheduleCard.js";

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

const serverCard = (extra = {}) => ({
  kind: "schedule",
  action: "register",
  title: "수진, 서연에게 공유해서 등록할까요?",
  lines: ["2026-10-31 18:00 엄마 생신 저녁 식사"],
  shared_with: ["수진", "서연"],
  pending_action: { type: "register", event_id: "", changes: {}, draft: { title: "엄마 생신 저녁 식사", date: "2026-10-31" } },
  ...extra,
});

test("서버의 확인 카드를 앱이 쓰는 모양으로 바꾼다", () => {
  const [card] = mapConfirmCards([serverCard()]);
  assert.equal(card.kind, "schedule");
  assert.equal(card.action, "register");
  assert.equal(card.title, "수진, 서연에게 공유해서 등록할까요?");
  assert.deepEqual(card.lines, ["2026-10-31 18:00 엄마 생신 저녁 식사"]);
  assert.deepEqual(card.sharedWith, ["수진", "서연"]);
  assert.equal(card.pendingAction.type, "register");
  assert.equal(card.status, CARD_PENDING);
  assert.equal(card.resultText, "");
});

test("부탁 카드(보내기·받는 사람 바꾸기·취소)도 변환하고 버튼이 다르다", () => {
  const request = (action, extra = {}) => ({
    kind: "schedule",
    action,
    title: "수진에게 부탁을 보낼까요?",
    lines: ["2026-10-31 15:00 장 같이 봐줘"],
    shared_with: ["수진"],
    pending_action: { type: action, request_id: "r1", to_ids: ["u2"] },
    ...extra,
  });
  const cards = mapConfirmCards([request("request_register"), request("request_edit"), request("request_cancel")]);
  assert.deepEqual(cards.map((c) => c.action), ["request_register", "request_edit", "request_cancel"]);
  assert.equal(cards[0].pendingAction.request_id, "r1");
  assert.deepEqual(cardButtons(cards[0]).map((b) => b.label), ["보내기", "취소"]);
  assert.deepEqual(cardButtons(cards[1]).map((b) => b.label), ["바꾸기", "취소"]);
  const cancel = cardButtons(cards[2]);
  assert.deepEqual(cancel.map((b) => b.label), ["부탁 취소하기", "돌아가기"]);
  assert.equal(cancel[0].tone, "danger");
});

test("모르는 종류·실행 정보가 없는 카드는 버리고, 목록이 아니면 빈 목록", () => {
  assert.deepEqual(mapConfirmCards(undefined), []);
  assert.deepEqual(mapConfirmCards(null), []);
  assert.deepEqual(mapConfirmCards("x"), []);
  const cards = mapConfirmCards([serverCard({ kind: "billing" }), serverCard({ action: "share" }), serverCard({ pending_action: null }), serverCard({ action: "delete", shared_with: undefined })]);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].action, "delete");
  assert.deepEqual(cards[0].sharedWith, []);
});

test("등록 카드의 버튼: 공유 대상이 있으면 공유/나만/취소, 없으면 등록/취소", () => {
  const withShare = mapConfirmCards([serverCard()])[0];
  assert.deepEqual(cardButtons(withShare).map((b) => [b.key, b.share]), [["share", true], ["mine", false], ["cancel", undefined]]);
  const alone = mapConfirmCards([serverCard({ shared_with: [] })])[0];
  assert.deepEqual(cardButtons(alone).map((b) => b.label), ["등록", "취소"]);
});

test("수정·삭제 카드의 버튼: 삭제는 위험 색, 취소는 항상 있다", () => {
  const del = mapConfirmCards([serverCard({ action: "delete", shared_with: [] })])[0];
  assert.deepEqual(cardButtons(del).map((b) => [b.label, b.tone]), [["삭제", "danger"], ["취소", "ghost"]]);
  const edit = mapConfirmCards([serverCard({ action: "edit", shared_with: [] })])[0];
  assert.deepEqual(cardButtons(edit).map((b) => b.label), ["바꾸기", "취소"]);
});

test("결과 문구: 서버 문장을 쓰고, 등록 카드가 있으면 공유한 사람 수를 덧붙인다", () => {
  assert.equal(confirmResultText({ text: "지웠어요.", cards: [] }), "지웠어요.");
  assert.equal(confirmResultText({ text: "등록했어요.", cards: [{ type: "registered", data: { shared: 2 } }] }), "등록했어요. (가족 2명에게도 공유했어요)");
  assert.equal(confirmResultText({ text: "등록했어요.", cards: [{ type: "registered", data: { shared: 0 } }] }), "등록했어요.");
  assert.equal(confirmResultText(null), "반영했어요.");
  assert.match(CANCELLED_TEXT, /취소/);
});

test("sendMessage: 확인 카드를 함께 돌려준다", async () => {
  const api = await import("../src/features/ai-assistant/api.js");
  globalThis.fetch = async () => json(200, { reply: "카드를 확인해 주세요", source: "ai", sources: [], confirm_cards: [serverCard()] });
  const res = await api.sendMessage("가족 모두에게 공유해서 일정 잡아줘", []);
  assert.equal(res.confirmCards.length, 1);
  assert.equal(res.confirmCards[0].sharedWith.length, 2);
  globalThis.fetch = async () => json(200, { reply: "안녕", source: "ai", sources: [] });
  assert.deepEqual((await api.sendMessage("안녕", [])).confirmCards, []);
});

test("confirmScheduleAction: 카드의 pending_action 과 share 를 그대로 확인 요청으로 보낸다", async () => {
  const api = await import("../src/features/ai-assistant/api.js");
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method, body: JSON.parse(init.body) });
    return json(200, { intent: "register", text: "등록했어요.", cards: [{ type: "registered", data: { shared: 2 } }] });
  };
  const card = mapConfirmCards([serverCard()])[0];
  const res = await api.confirmScheduleAction(card, true);
  assert.equal(calls[0].url, "http://api.test/schedule/agent/confirm");
  assert.equal(calls[0].method, "POST");
  assert.deepEqual(calls[0].body, { action: card.pendingAction, share: true });
  assert.equal(res.text, "등록했어요. (가족 2명에게도 공유했어요)");
  await api.confirmScheduleAction(card, false);
  assert.equal(calls[1].body.share, false);
});

test("confirmScheduleAction: 서버가 거절하면 그 메시지를 그대로 던진다(카드에 보이고 다시 누를 수 있다)", async () => {
  const api = await import("../src/features/ai-assistant/api.js");
  globalThis.fetch = async () => json(400, { code: "draft_incomplete", message: "등록에 필요한 제목이나 날짜가 없어요" });
  const card = mapConfirmCards([serverCard()])[0];
  await assert.rejects(() => api.confirmScheduleAction(card, true), (e) => e.code === "draft_incomplete" && /제목/.test(e.message));
});

test("askAssistantInRoom: 방에서 부른 요청의 확인 카드도 돌려준다(질문한 사람 화면에만 보인다)", async () => {
  const fam = await import("../src/features/family-chat/api.js");
  globalThis.fetch = async () =>
    json(200, { reply: "카드를 확인해 주세요", visibility: "private", private_reasons: ["확인 버튼이 필요한 제안"], posted_message_id: null, confirm_cards: [serverCard()] });
  const res = await fam.askAssistantInRoom("가족 모두에게 공유해서 일정 잡아줘", []);
  assert.equal(res.visibility, "private");
  assert.equal(res.postedMessageId, null);
  assert.equal(res.confirmCards.length, 1);
  assert.equal(res.confirmCards[0].action, "register");
});

const proposal = (extra = {}) => ({ token: "signed.token.value", summary: "지출 등록: 치과 50,000원", tab: "billing", ...extra });

test("정산·돌봄 제안을 카드로 바꾸고, 토큰이 없거나 모르는 탭은 버린다", () => {
  const cards = mapProposals([proposal(), proposal({ tab: "care", summary: "식단 기록: 점심 김치찌개" }), proposal({ token: "" }), proposal({ tab: "schedule" }), null]);
  assert.equal(cards.length, 2);
  assert.deepEqual(cards[0], {
    kind: "proposal",
    action: "propose",
    tab: "billing",
    title: "정산 에이전트의 제안",
    lines: ["지출 등록: 치과 50,000원"],
    sharedWith: [],
    token: "signed.token.value",
    status: CARD_PENDING,
    resultText: "",
  });
  assert.equal(cards[1].title, "안부 에이전트의 제안");
  assert.deepEqual(mapProposals(undefined), []);
  assert.deepEqual(mapProposals("x"), []);
});

test("제안 카드의 버튼은 확인/취소이고, 채팅 카드는 일정 카드 뒤에 제안이 온다", () => {
  const [card] = mapProposals([proposal()]);
  assert.deepEqual(cardButtons(card).map((b) => b.key), ["ok", "cancel"]);
  const all = mapChatCards({ confirm_cards: [serverCard()], proposals: [proposal()] });
  assert.deepEqual(all.map((c) => c.kind), ["schedule", "proposal"]);
  assert.deepEqual(mapChatCards({}), []);
  assert.deepEqual(mapChatCards(null), []);
});

test("sendMessage: 정산·돌봄 제안도 확인 카드로 돌려준다", async () => {
  const api = await import("../src/features/ai-assistant/api.js");
  globalThis.fetch = async () => json(200, { reply: "등록할까요?", sources: [], confirm_cards: [], proposals: [proposal()] });
  const res = await api.sendMessage("치과 5만원 지출 등록해줘");
  assert.equal(res.confirmCards.length, 1);
  assert.equal(res.confirmCards[0].kind, "proposal");
});

test("confirmCardAction: 제안은 그 탭의 확인 요청에 token 만 보낸다", async () => {
  const api = await import("../src/features/ai-assistant/api.js");
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: JSON.parse(init.body) });
    return json(200, { ok: true, summary: "지출 등록: 치과 50,000원" });
  };
  const [billing] = mapProposals([proposal()]);
  const out = await api.confirmCardAction(billing, true);
  assert.equal(calls[0].url, "http://api.test/billing/agent/confirm");
  assert.deepEqual(calls[0].body, { token: "signed.token.value" });
  assert.equal(out.text, "반영했어요 · 지출 등록: 치과 50,000원");
  const [care] = mapProposals([proposal({ tab: "care" })]);
  await api.confirmCardAction(care, false);
  assert.equal(calls[1].url, "http://api.test/care/agent/confirm");
});

test("confirmCardAction: 일정 카드는 예전처럼 일정 확인 요청으로 간다", async () => {
  const api = await import("../src/features/ai-assistant/api.js");
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), body: JSON.parse(init.body) });
    return json(200, { text: "등록했어요.", cards: [] });
  };
  const [card] = mapConfirmCards([serverCard()]);
  await api.confirmCardAction(card, true);
  assert.equal(calls[0].url, "http://api.test/schedule/agent/confirm");
  assert.equal(calls[0].body.share, true);
});

test("confirmCardAction: 서버가 거절하면(만료·이미 처리) 그 메시지를 그대로 던진다", async () => {
  const api = await import("../src/features/ai-assistant/api.js");
  globalThis.fetch = async () => json(409, { code: "proposal_used", message: "이미 처리한 요청이에요" });
  const [card] = mapProposals([proposal()]);
  await assert.rejects(() => api.confirmCardAction(card, false), (e) => /이미 처리/.test(e.message));
});
