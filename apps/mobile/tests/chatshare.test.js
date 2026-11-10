// 채팅방 공유 카드(일정·정산) 말풍선: 카드 판별·문구 포맷터, 메뉴 항목, 삭제 표시, 말풍선 분기(소스 구조): npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { mergeMessages } from "../src/features/family-chat/chatUtils.js";
import { markDeleted, menuKeys, refreshExisting } from "../src/features/family-chat/messageActions.js";
import {
  SETTLEMENT_LINES_SHOWN,
  eventCardView,
  formatShareDate,
  formatShareMoney,
  formatShareMonth,
  formatShareTime,
  isShareMessage,
  settlementCardView,
  shareA11yLabel,
} from "../src/features/family-chat/shareUtils.js";

const read = (rel) => readFileSync(new URL(`../src/features/family-chat/${rel}`, import.meta.url), "utf8");

const eventShare = (over = {}) => ({
  kind: "event",
  payload: { title: "치과 예약", date: "2026-11-12", start_time: "15:00", end_time: "16:30", place: "우리치과", kind: 1, with_names: [], ...over },
});
const settleShare = (over = {}) => ({
  kind: "settlement",
  payload: { month: "2026-11", remaining: 12000, lines: [{ direction: "receive", name: "수진", amount: 12000 }], ...over },
});
const cardMessage = (share, over = {}) => ({ id: 7, user_id: "me", user_name: "나", text: "일정을 공유했어요", created_at: "2026-11-10T01:00:00Z", reactions: [], share, ...over });

test("isShareMessage: 알려진 종류의 카드(payload 가 객체)이고 지우지 않았을 때만 true", () => {
  assert.equal(isShareMessage(cardMessage(eventShare())), true);
  assert.equal(isShareMessage(cardMessage(settleShare())), true);
  assert.equal(isShareMessage(cardMessage(null)), false);
  assert.equal(isShareMessage({ id: 1, text: "안녕" }), false);
  assert.equal(isShareMessage(cardMessage({ kind: "report", payload: {} })), false); // 모르는 종류는 일반 글 말풍선으로 둔다
  assert.equal(isShareMessage(cardMessage({ kind: "event", payload: null })), false);
  assert.equal(isShareMessage(cardMessage(eventShare(), { deleted: true })), false);
  assert.equal(isShareMessage(null), false);
});

test("formatShareDate: 'M월 D일 (요일)', 형식이 틀리거나 비면 빈 문구", () => {
  assert.equal(formatShareDate("2026-11-12"), "11월 12일 (목)");
  assert.equal(formatShareDate("2026-01-05"), "1월 5일 (월)");
  assert.equal(formatShareDate(null), "");
  assert.equal(formatShareDate("내일"), "");
  assert.equal(formatShareDate("2026-13-40"), "");
});

test("formatShareTime: 시작만/시작~끝/없음(종일), 24시간 값은 오전·오후로", () => {
  assert.equal(formatShareTime("15:00", "16:30"), "오후 3:00 ~ 오후 4:30");
  assert.equal(formatShareTime("09:05", null), "오전 9:05");
  assert.equal(formatShareTime("00:00", "12:00"), "오전 12:00 ~ 오후 12:00");
  assert.equal(formatShareTime("15:00:00", null), "오후 3:00"); // 초가 붙어도 된다
  assert.equal(formatShareTime(null, null), "종일");
  assert.equal(formatShareTime(null, "16:00"), "종일"); // 시작이 없으면 끝만으로는 시간 범위를 만들지 않는다
  assert.equal(formatShareTime("25:99", null), "종일");
});

test("eventCardView: 약속·할 일 라벨, 날짜·시간·장소·같이하는 사람", () => {
  const v = eventCardView(eventShare().payload);
  assert.deepEqual(v, { badge: "약속", title: "치과 예약", when: "11월 12일 (목) · 오후 3:00 ~ 오후 4:30", place: "우리치과", withText: "" });
  assert.equal(eventCardView({ ...eventShare().payload, kind: 2 }).badge, "할 일");
  assert.equal(eventCardView({ ...eventShare().payload, kind: 9 }).badge, "약속"); // 모르는 값은 약속
});

test("eventCardView: 날짜가 없거나(null) 시간·장소가 비어도 깨지지 않는다", () => {
  const v = eventCardView({ title: "  ", date: null, start_time: null, end_time: null, place: "  ", kind: 2, with_names: null });
  assert.equal(v.title, "(제목 없음)");
  assert.equal(v.when, "날짜 미정");
  assert.equal(v.place, "");
  assert.equal(v.withText, "");
  assert.equal(eventCardView({ title: "산책", date: "2026-11-12", start_time: null, end_time: null, place: null, kind: 1, with_names: [] }).when, "11월 12일 (목) · 종일");
  assert.equal(eventCardView({ title: "산책", date: null, start_time: "10:00", end_time: null, place: null, kind: 1, with_names: [] }).when, "날짜 미정 · 오전 10:00");
  assert.doesNotThrow(() => eventCardView({}));
  assert.doesNotThrow(() => eventCardView(null));
});

test("eventCardView: 같이하는 사람 이름 0명·1명·여러 명(3명까지 보이고 나머지는 '외 N명')", () => {
  const names = (list) => eventCardView({ ...eventShare().payload, with_names: list }).withText;
  assert.equal(names([]), "");
  assert.equal(names(["수진"]), "함께 수진");
  assert.equal(names(["수진", "민수", "하늘"]), "함께 수진, 민수, 하늘");
  assert.equal(names(["수진", "민수", "하늘", "보라", "달"]), "함께 수진, 민수, 하늘 외 2명");
  assert.equal(names(["수진", "", "  ", null]), "함께 수진"); // 빈 이름은 건너뛴다
});

test("formatShareMoney·formatShareMonth: 천 단위 쉼표, 음수는 절댓값, 월은 'YYYY년 M월'", () => {
  assert.equal(formatShareMoney(12000), "12,000원");
  assert.equal(formatShareMoney(-1234567), "1,234,567원");
  assert.equal(formatShareMoney(0), "0원");
  assert.equal(formatShareMoney(null), "");
  assert.equal(formatShareMoney("abc"), "");
  assert.equal(formatShareMonth("2026-11"), "2026년 11월");
  assert.equal(formatShareMonth("2026-03"), "2026년 3월");
  assert.equal(formatShareMonth("2026-13"), "");
  assert.equal(formatShareMonth(null), "");
});

test("settlementCardView: 받을 돈(+)·보낼 돈(−)·0, 줄 문구(보내요·받아요)", () => {
  const recv = settlementCardView(settleShare().payload);
  assert.equal(recv.month, "2026년 11월");
  assert.deepEqual(recv.summary, { tone: "receive", text: "받을 돈 12,000원" });
  assert.deepEqual(recv.lines, [{ key: "0", text: "수진님에게 12,000원 받아요" }]);
  assert.equal(recv.moreCount, 0);

  const send = settlementCardView(settleShare({ remaining: -5000, lines: [{ direction: "send", name: "민수", amount: 5000 }] }).payload);
  assert.deepEqual(send.summary, { tone: "send", text: "보낼 돈 5,000원" });
  assert.deepEqual(send.lines, [{ key: "0", text: "민수님에게 5,000원 보내요" }]);

  const even = settlementCardView(settleShare({ remaining: 0, lines: [] }).payload);
  assert.deepEqual(even.summary, { tone: "even", text: "정산할 돈이 없어요" });
  assert.deepEqual(even.lines, []);
});

test("settlementCardView: 줄은 최대 SETTLEMENT_LINES_SHOWN 개까지 보이고 나머지는 moreCount, 이상한 줄은 건너뛴다", () => {
  const many = Array.from({ length: SETTLEMENT_LINES_SHOWN + 3 }, (_, i) => ({ direction: "send", name: `사람${i}`, amount: 1000 }));
  const v = settlementCardView(settleShare({ remaining: -9000, lines: many }).payload);
  assert.equal(v.lines.length, SETTLEMENT_LINES_SHOWN);
  assert.equal(v.moreCount, 3);
  const odd = settlementCardView(settleShare({ lines: [null, { direction: "send", name: "", amount: 2000 }, { direction: "send", name: "x", amount: "큰돈" }, { direction: "receive", name: "수진", amount: 3000 }] }).payload);
  assert.deepEqual(odd.lines.map((l) => l.text), ["상대님에게 2,000원 보내요", "수진님에게 3,000원 받아요"]);
  assert.doesNotThrow(() => settlementCardView({}));
  assert.doesNotThrow(() => settlementCardView(null));
});

test("shareA11yLabel: 일정·정산 카드의 읽어 주는 문구", () => {
  assert.equal(shareA11yLabel(eventShare()), "일정 공유 카드, 약속, 치과 예약, 11월 12일 (목) · 오후 3:00 ~ 오후 4:30, 장소 우리치과");
  assert.equal(shareA11yLabel(eventShare({ with_names: ["수진"], place: "" })), "일정 공유 카드, 약속, 치과 예약, 11월 12일 (목) · 오후 3:00 ~ 오후 4:30, 함께 수진");
  assert.equal(shareA11yLabel(settleShare()), "정산 공유 카드, 2026년 11월, 받을 돈 12,000원, 수진님에게 12,000원 받아요");
  assert.equal(shareA11yLabel(settleShare({ remaining: 0, lines: [] })), "정산 공유 카드, 2026년 11월, 정산할 돈이 없어요");
});

test("menuKeys: 카드에는 공지(pin)·복사가 없고 반응·답장은 있다. 삭제는 내 카드에만", () => {
  const card = cardMessage(eventShare());
  assert.deepEqual(menuKeys({ message: card, myId: "other" }), ["reactions", "reply"]);
  assert.deepEqual(menuKeys({ message: card, myId: "me" }), ["reactions", "reply", "delete"]);
  assert.deepEqual(menuKeys({ message: cardMessage(settleShare()), myId: "me", pinned: true }), ["reactions", "reply", "delete"]);
  // 일반 글은 그대로
  assert.deepEqual(menuKeys({ message: { id: 8, user_id: "me", text: "안녕", reactions: [] }, myId: "me" }), ["reactions", "reply", "pin", "copy", "delete"]);
});

test("markDeleted: 지우면 카드 내용(share)도 비운다", () => {
  const gone = markDeleted(cardMessage(eventShare()));
  assert.equal(gone.deleted, true);
  assert.equal(gone.share, null);
  assert.equal(isShareMessage(gone), false);
});

test("목록 병합·새로고침: share 가 유지되고, 서버가 지운 카드는 삭제 표시로 바뀐다", () => {
  const card = cardMessage(eventShare());
  const merged = mergeMessages([], [card]);
  assert.deepEqual(merged[0].share, card.share);
  const again = refreshExisting(merged, [{ ...card }]);
  assert.equal(again, merged); // 바뀐 것이 없으면 같은 배열
  const deletedFresh = { ...card, deleted: true, text: "", share: null };
  const next = refreshExisting(merged, [deletedFresh]);
  assert.equal(next[0].deleted, true);
  assert.equal(next[0].share, null);
});

test("MessageBubble: 카드이면 ShareCard 를 그리고 본문 글자는 그리지 않으며, 메뉴·하트는 바깥 말풍선이 받고 읽어 주는 문구를 붙인다", () => {
  const bubble = read("components/MessageBubble.js");
  assert.match(bubble, /import ShareCard from "\.\/ShareCard"/);
  assert.match(bubble, /isShareMessage/);
  assert.match(bubble, /\{isShare \? <ShareCard share=\{message\.share\} \/> : null\}/);
  assert.match(bubble, /accessibilityLabel: shareA11yLabel\(message\.share\)/); // 바깥 말풍선이 하나로 묶여도 카드 문구를 읽는다
  assert.match(bubble, /\{message\.text && !isShare \? \(/); // 고정 문구("일정을 공유했어요")는 카드 위에 또 보이지 않는다
});

test("ShareCard: 화면 값은 theme 토큰만, 서버 호출 없음, 터치를 가로채지 않는 View, 일정·정산 두 모양", () => {
  const card = read("components/ShareCard.js");
  assert.doesNotMatch(card, /#[0-9a-fA-F]{3,8}\b/); // 색 하드코딩 금지
  assert.doesNotMatch(card, /fetch\(|apiFetch/);
  assert.match(card, /from "@\/theme"/);
  assert.doesNotMatch(card, /Pressable/); // 안쪽 Pressable 이 길게 누르기·더블탭 하트를 가로채지 않는다
  assert.match(card, /share\.kind === "settlement"/);
  assert.match(card, /accessibilityLabel=\{shareA11yLabel\(share\)\}/);
});
