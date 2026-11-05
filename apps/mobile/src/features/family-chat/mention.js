// 가족 채팅방에서 @가비 로 부르기(순수 함수, 시험: tests/mention.test.js)
// 서버는 POST /ai-assistant/chat 에 audience: "room" 으로 받아 답을 가비 이름으로 가족 전체방에 직접 저장한다(모두에게 공유, 기록으로 남는다).
// 이 앱이 목록 사이에 끼워 보이는 항목은 답을 기다리는 중·안내·오류·확인 카드뿐이다(서버에 남지 않는다).

import { parseTime } from "./chatUtils";

export const MENTION = "@가비";
export const ASSISTANT_NAME = "가비";
export const LOCAL_ASSISTANT_ID = "assistant-local"; // 내 화면에만 보이는 답의 보낸 사람 표시(실제 사용자 id 가 아니다)

const MAX_TURNS = 6; // 서버에 보내는 앞 대화는 내가 @가비 로 나눈 최근 몇 턴만
const THREAD_MS = 15 * 60 * 1000; // 이 시간이 지난 대화는 이어 가지 않는다
const PAIR_GAP_MS = 2 * 60 * 1000; // 질문과 가비의 답이 이 시간 안에 이어져야 한 쌍으로 본다(답은 보통 몇 초 안에 올라온다)
/**
 * 입력창에 `@` 를 치면 보여 주는 @가비 기능 예시. 서버가 실제로 처리하는 영역만 둔다(날씨·일반 질문은 처리하지 않는다).
 * 서버 근거: ai_assistant/agents.py(탭 에이전트), ai_assistant/knowledge/rag_chat.py, family_chat/agent.py. 바꿀 때는 서버와 대조한다.
 */
export const MENTION_EXAMPLES = [
  { key: "spend", category: "지출", text: "@가비 이번 달 지출 알려줘" },
  { key: "schedule", category: "일정", text: "@가비 내일 일정 알려줘" },
  { key: "schedule-add", category: "일정 등록", text: "@가비 토요일 저녁 가족 식사 일정 넣어줘" },
  { key: "chat-search", category: "채팅 검색", text: "@가비 채팅에서 병원 얘기 언제 했지?" },
  { key: "chat-summary", category: "채팅 요약", text: "@가비 요즘 채팅 요약해줘" },
  { key: "document", category: "문서", text: "@가비 올려 둔 영수증 찾아줘" },
];
export const EMPTY_QUESTION_HINT = `@가비 뒤에 물어볼 내용을 적어 주세요. 예: ${MENTION_EXAMPLES[0].text}`;

const LEADING = /^\s*@가비(?![0-9A-Za-z가-힣_])[\s,.:;!?]*/;

/**
 * 글이 @가비 로 시작하는지와 가비에게 물을 내용.
 * 글 중간의 @가비 는 부르는 것으로 보지 않는다(다른 사람에게 하는 말일 수 있다). "@가비야" 처럼 이어 붙은 글자는 이름이 아니라 부르는 말로 보지 않는다.
 * @param {string} text
 * @returns {{ mentioned: boolean, question: string }}
 */
export function parseMention(text) {
  const raw = String(text ?? "");
  const m = LEADING.exec(raw);
  if (!m) return { mentioned: false, question: "" };
  return { mentioned: true, question: raw.slice(m[0].length).trim() };
}

const HINT_TYPING = /^@(?:[ㄱ\uAC00-\uAE4B]|가ㅂ|가비)?$/; // `@`, `@ㄱ`, ㄱ으로 시작하는 한 글자(가~깋), `@가ㅂ`, `@가비`

/**
 * 예시 목록을 보일지: 글(앞뒤 공백 제외)이 `@`, 한글 조합 중간(`@ㄱ`·`@갑`·`@가ㅂ`), `@가비` 이거나 `@가비` 뒤에 질문이 비어 있을 때만.
 * @param {string} text 입력창 글
 * @returns {boolean}
 */
export function mentionHintsVisible(text) {
  const t = String(text ?? "").trim();
  if (HINT_TYPING.test(t)) return true; // 한글 조합 중간 상태(@ㄱ, @갑, @가ㅂ)도 목록이 깜빡이지 않게 보인다
  const p = parseMention(t);
  return p.mentioned && p.question === "";
}

/**
 * 서버에 보낼 앞 대화: 내가 @가비 로 나눈 최근 대화만(방의 다른 사람 글은 넣지 않는다).
 * @param {{ role: "user" | "assistant", text: string, at: number }[]} thread
 * @param {number} [now]
 * @returns {{ role: "user" | "assistant", text: string }[]}
 */
export function mentionHistory(thread, now = Date.now()) {
  const fresh = thread.filter((t) => now - t.at <= THREAD_MS).slice(-MAX_TURNS);
  return fresh.map((t) => ({ role: t.role, text: t.text }));
}

/**
 * 방에 저장된 메시지로 이전 @가비 대화를 되살린다(방을 나갔다 들어와도 이어 가도록). 내가 쓴 `@가비 질문` 바로 다음 메시지가
 * 가비의 답이고 2분 안에 올라왔을 때만 한 쌍으로 본다. 사이에 다른 사람 글이 끼거나, 바로 앞에도 누군가의 @가비 질문이 있어 답이 뒤바뀔 수
 * 있으면 건너뛴다(남의 답을 내 이전 대화로 되살리지 않는다). 지운 글·전송 중인 글은 뺀다.
 * 시각은 가비 답의 시각이라 15분이 지난 쌍은 mentionHistory 가 버린다.
 * @param {{ id?: number, user_id: string, text?: string, created_at: string, is_assistant?: boolean, deleted?: boolean, clientId?: string }[]} messages 오래된 순
 * @param {string | null | undefined} myId 내 사용자 id
 * @returns {{ role: "user" | "assistant", text: string, at: number }[]}
 */
export function restoreThread(messages, myId) {
  const list = (messages ?? []).filter((m) => !m.clientId);
  const thread = [];
  for (let i = 0; i < list.length - 1; i++) {
    const ask = list[i];
    const answer = list[i + 1];
    if (!myId || ask.user_id !== myId || ask.is_assistant || ask.deleted) continue;
    if (!answer.is_assistant || answer.deleted || !answer.text) continue;
    const called = parseMention(ask.text);
    if (!called.mentioned || !called.question) continue;
    const before = list[i - 1];
    if (before && !before.is_assistant && !before.deleted && parseMention(before.text).mentioned) continue; // 동시에 부른 질문이 있어 짝이 뒤바뀔 수 있다
    const at = parseTime(answer.created_at);
    const gap = at - parseTime(ask.created_at);
    if (!(gap >= 0 && gap <= PAIR_GAP_MS)) continue;
    thread.push({ role: "user", text: called.question, at }, { role: "assistant", text: answer.text, at });
  }
  return thread.slice(-MAX_TURNS * 2);
}

/** 대화에 한 턴을 더한다(오래된 것은 버린다). */
export function pushThread(thread, ...turns) {
  return [...thread, ...turns].slice(-MAX_TURNS * 2);
}

/**
 * 내 화면에만 보이는 가비 항목.
 * pending(답 기다림) · cards(방에 저장된 답에 딸린 확인 카드) · reply(방에 저장되지 않은 답, 구 서버) · info(안내) · error(오류)
 * @param {{ id: string, state: "pending" | "cards" | "reply" | "info" | "error", text?: string, question?: string, confirmCards?: object[], createdAt?: string }} p
 */
export function makeNote({ id, state, text = "", question = "", confirmCards = [], createdAt = new Date().toISOString() }) {
  return {
    id,
    localNote: true,
    state,
    user_id: LOCAL_ASSISTANT_ID,
    user_name: ASSISTANT_NAME,
    text,
    question,
    confirmCards, // 확인 버튼이 필요한 일정 요청(가족 공유 등록·수정·삭제). 질문한 사람 화면에만 보인다
    created_at: createdAt,
  };
}

/**
 * 서버 메시지 목록에 내 화면에만 보이는 가비 항목을 시간순으로 끼운다. 같은 시각이면 메시지 뒤에 둔다.
 * 원래 목록(읽음 처리·새 메시지 확인에 쓰는 것)은 바꾸지 않는다.
 * @param {object[]} messages 오름차순
 * @param {object[]} notes 오름차순
 * @returns {object[]}
 */
export function mergeNotes(messages, notes) {
  if (!notes.length) return messages;
  const out = [];
  let i = 0;
  const sorted = [...notes].sort((a, b) => parseTime(a.created_at) - parseTime(b.created_at));
  for (const m of messages) {
    while (i < sorted.length && parseTime(sorted[i].created_at) < parseTime(m.created_at)) out.push(sorted[i++]);
    out.push(m);
  }
  while (i < sorted.length) out.push(sorted[i++]);
  return out;
}
