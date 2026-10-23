import { useSyncExternalStore } from "react";

import { answerFor } from "./agent";
import { getScheduleItems } from "./store";
import { todayKey } from "./utils/date";

// 서버 연동 전까지 쓰는 메모리 저장소. 채팅 대화와 기록을 하단 시트·채팅 화면·기록 화면이 같이 본다.
// 서버가 붙으면 이 파일의 함수 본문만 api.js 호출로 바꾸고 화면은 그대로 둔다.

/** 마지막 대화 뒤 이 시간이 지나면 새 대화로 시작한다(이전 대화는 기록에 남는다). */
const FRESH_MS = 24 * 60 * 60 * 1000;
/** 답을 쓰는 척 점 세 개를 보여 주는 시간(ms). */
const THINKING_MS = 900;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * @typedef {Object} ChatMessage
 * @property {string} id
 * @property {"user" | "ai"} role
 * @property {string} text
 * @property {import("./model").ScheduleItem[]} [items] 답에 붙은 약속·할 일 미니 카드
 * @property {{ name: string, draft: { kind: string, title: string, daysFromToday: number } }} [suggestion] 추가해 드릴까요? 제안
 * @property {boolean} [later] 제안에서 "나중에"를 누른 상태
 * @property {boolean} [error] 답하지 못한 말풍선(다시 시도 버튼이 붙는다)
 */

/**
 * @typedef {Object} Conversation
 * @property {string} id
 * @property {ChatMessage[]} messages
 * @property {number} updatedAt 마지막 대화 시각(밀리초)
 */

let nextId = 100;
const makeId = (prefix) => `${prefix}${(nextId += 1)}`;

/** 기록 화면에서 보이는 지난 대화 샘플(오늘 기준 상대 날짜). @returns {Conversation[]} */
function createMockConversations() {
  const now = Date.now();
  const at = (daysAgo, hour, minute) => {
    const d = new Date(now - daysAgo * DAY_MS);
    d.setHours(hour, minute, 0, 0);
    return d.getTime();
  };
  const talk = (id, daysAgo, hour, minute, question, answer) => ({
    id,
    updatedAt: at(daysAgo, hour, minute),
    messages: [
      { id: `${id}-q`, role: "user", text: question },
      { id: `${id}-a`, role: "ai", text: answer },
    ],
  });
  return [
    talk("h1", 1, 18, 40, "우선순위 정해줘", "어제는 병원 방문을 먼저 챙기시라고 말씀드렸어요."),
    talk("h2", 5, 10, 5, "빈 시간 찾아줘", "그날은 오후 2시부터 5시까지 비어 있었어요."),
    talk("h3", 9, 9, 30, "이번 주 일정 알려줘", "그 주에는 일정이 3개 있었어요."),
    talk("h4", 14, 20, 15, "병원 일정 알려줘", "병원 관련은 2개였어요."),
    talk("h5", 20, 8, 50, "가족 모임 언제야?", "가족 모임은 그달 말이었어요."),
  ];
}

const emptyConversation = () => ({ id: makeId("c"), messages: [], updatedAt: Date.now() });

let state = (() => {
  const fresh = emptyConversation();
  return { conversations: [fresh, ...createMockConversations()], currentId: fresh.id, thinking: false, resumed: false };
})();
const listeners = new Set();

const emit = () => listeners.forEach((fn) => fn());
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
const set = (next) => {
  state = { ...state, ...next };
  emit();
};
const patchCurrent = (patch) =>
  set({ conversations: state.conversations.map((c) => (c.id === state.currentId ? { ...c, ...patch } : c)) });
const current = () => state.conversations.find((c) => c.id === state.currentId);

/** @returns {{ messages: ChatMessage[], thinking: boolean }} 지금 열린 대화 */
export function useChat() {
  const snapshot = useSyncExternalStore(subscribe, () => state);
  const conversation = snapshot.conversations.find((c) => c.id === snapshot.currentId);
  return { messages: conversation?.messages ?? [], thinking: snapshot.thinking };
}

/** @returns {Conversation[]} 기록에 보이는 대화(말이 한 번이라도 오간 것), 최근 순 */
export function useConversations() {
  const snapshot = useSyncExternalStore(subscribe, () => state);
  return snapshot.conversations.filter((c) => c.messages.length > 0).sort((a, b) => b.updatedAt - a.updatedAt);
}

const answer = (question) => {
  const result = answerFor(question, getScheduleItems(), todayKey());
  patchCurrent({ messages: [...current().messages, { id: makeId("m"), role: "ai", ...result }], updatedAt: Date.now() });
  set({ thinking: false });
};

/**
 * 질문을 보낸다. 마지막 대화 뒤 하루가 지났으면 새 대화로 시작하고, 답은 점 세 개를 잠깐 보여 준 뒤 붙는다.
 * @param {string} text
 */
export function sendMessage(text) {
  const question = text.trim();
  if (!question || state.thinking) return;
  // 기록에서 열어 이어 가는 대화는 시간이 지나도 그대로 이어 간다.
  if (!state.resumed && current().messages.length > 0 && Date.now() - current().updatedAt > FRESH_MS) newChat();
  patchCurrent({ messages: [...current().messages, { id: makeId("m"), role: "user", text: question }], updatedAt: Date.now() });
  set({ thinking: true });
  setTimeout(() => answer(question), THINKING_MS);
}

/** 답하지 못한 말풍선을 지우고 마지막 질문을 다시 보낸다. */
export function retryLast() {
  const messages = current().messages;
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  if (!lastUser || state.thinking) return;
  patchCurrent({ messages: messages.filter((m) => !m.error) });
  set({ thinking: true });
  setTimeout(() => answer(lastUser.text), THINKING_MS);
}

/** 새 대화를 시작한다. 지금 대화는 기록에 그대로 남는다(비어 있었으면 그 빈 대화를 다시 쓴다). */
export function newChat() {
  if (current().messages.length === 0) return;
  const fresh = emptyConversation();
  set({ conversations: [fresh, ...state.conversations], currentId: fresh.id, thinking: false, resumed: false });
}

/** 기록의 대화를 열어 이어서 대화한다. @param {string} id */
export function openConversation(id) {
  if (state.conversations.some((c) => c.id === id)) set({ currentId: id, thinking: false, resumed: true });
}

/** 제안 카드의 "나중에"를 누르거나 푼다. @param {string} messageId */
export function toggleSuggestionLater(messageId) {
  patchCurrent({ messages: current().messages.map((m) => (m.id === messageId ? { ...m, later: !m.later } : m)) });
}
