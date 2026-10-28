// 채팅의 일정 확인 카드(가족 공유 등록·수정·삭제): 서버 응답 변환, 버튼, 결과 문구, 확인 요청 모양을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  CANCELLED_TEXT,
  CARD_PENDING,
  cardButtons,
  confirmResultText,
  mapConfirmCards,
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
