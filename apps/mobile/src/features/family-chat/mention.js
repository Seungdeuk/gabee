// 가족 채팅방에서 @가비 로 부르기(순수 함수, 시험: tests/mention.test.js)
// 서버는 POST /ai-assistant/chat 에 audience: "room" 으로 받아 방에 올려도 되면(visibility=room) 가비 이름으로 직접 저장하고,
// 개인용(private)이면 저장하지 않는다. 개인용 답은 이 앱이 질문한 사람 화면에만 목록 사이에 끼워 보여 준다(서버에 남지 않는다).

import { parseTime } from "./chatUtils";

export const MENTION = "@가비";
export const ASSISTANT_NAME = "가비";
export const LOCAL_ASSISTANT_ID = "assistant-local"; // 내 화면에만 보이는 답의 보낸 사람 표시(실제 사용자 id 가 아니다)

const MAX_TURNS = 6; // 서버에 보내는 앞 대화는 내가 @가비 로 나눈 최근 몇 턴만
const THREAD_MS = 15 * 60 * 1000; // 이 시간이 지난 대화는 이어 가지 않는다
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
export const DIRECT_NOT_ALLOWED = "1:1 대화에서는 @가비를 쓸 수 없어요. 가족 전체 채팅방에서 불러 주세요.";

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
 * 예시 목록을 보일지: 글(앞뒤 공백 제외)이 `@`, 한글 조합 중간(`@ㄱ`·`@갑`·`@가ㅂ`), `@가비` 이거나 `@가비` 뒤에 질문이 비어 있을 때만. 1:1 방에서는 가비를 부를 수 없으니 항상 false.
 * @param {string} text 입력창 글
 * @param {boolean} [direct] 1:1 방이면 true
 * @returns {boolean}
 */
export function mentionHintsVisible(text, direct = false) {
  if (direct) return false;
  const t = String(text ?? "").trim();
  if (HINT_TYPING.test(t)) return true; // 한글 조합 중간 상태(@ㄱ, @갑, @가ㅂ)도 목록이 깜빡이지 않게 보인다
  const p = parseMention(t);
  return p.mentioned && p.question === "";
}

/**
 * 서버에 보낼 앞 대화: 내가 @가비 로 나눈 최근 대화만(방의 다른 사람 글은 넣지 않는다).
 * 개인용이라 나에게만 보였던 가비의 답에는 private 표시를 단다. 서버는 이 표시가 하나라도 있으면 이번 답도 방에 올리지 않는다.
 * @param {{ role: "user" | "assistant", text: string, at: number, private?: boolean }[]} thread
 * @param {number} [now]
 * @returns {{ role: "user" | "assistant", text: string, private?: boolean }[]}
 */
export function mentionHistory(thread, now = Date.now()) {
  const fresh = thread.filter((t) => now - t.at <= THREAD_MS).slice(-MAX_TURNS);
  return fresh.map((t) => (t.private ? { role: t.role, text: t.text, private: true } : { role: t.role, text: t.text }));
}

/** 대화에 한 턴을 더한다(오래된 것은 버린다). */
export function pushThread(thread, ...turns) {
  return [...thread, ...turns].slice(-MAX_TURNS * 2);
}

/**
 * 개인용으로 판단된 이유 한 줄. 이유 글은 서버가 정한다.
 * @param {string[] | undefined} reasons
 * @returns {string}
 */
export function privateNotice(reasons) {
  const why = (reasons ?? []).filter(Boolean);
  return why.length ? `개인 정보가 있어서 방에 올리지 않았어요 · ${why.join(", ")}` : "개인 정보가 있어서 방에 올리지 않았어요";
}

/**
 * 내 화면에만 보이는 가비 항목(답 기다림·개인용 답·안내·오류).
 * @param {{ id: string, state: "pending" | "private" | "info" | "error", text?: string, reasons?: string[], question?: string, confirmCards?: object[], createdAt?: string }} p
 */
export function makeNote({ id, state, text = "", reasons = [], question = "", confirmCards = [], createdAt = new Date().toISOString() }) {
  return {
    id,
    localNote: true,
    state,
    user_id: LOCAL_ASSISTANT_ID,
    user_name: ASSISTANT_NAME,
    text,
    reasons,
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
