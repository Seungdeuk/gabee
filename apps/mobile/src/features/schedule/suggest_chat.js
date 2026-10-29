// 추천 요청에 싣는 "최근 내가 AI 채팅에 한 말". 서버에 저장하지 않는 값이라 이 요청 말고는 어디에도 따로 저장·전송하지 않는다.
export const CHAT_DAYS = 7;
export const CHAT_MAX_LINES = 30;
export const CHAT_MAX_CHARS = 200;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * 개인 AI 채팅에서 내가 보낸 말을 최근 것부터 골라 추천 요청용 줄로 만든다.
 * 메시지에는 시각 필드가 없어(있으면 at·createdAt 을 쓴다) 보통 그 대화의 updatedAt 을 시각으로 쓴다.
 * 최근 7일 이내만, 앞뒤 공백을 다듬고 200자로 자르고, 빈 줄과 같은 문장 반복은 버리고, 최대 30줄.
 * @param {{ updatedAt?: number, messages?: { role?: string, text?: string, at?: number, createdAt?: number }[] }[]} sessions loadSessions 의 결과
 * @param {number} now 지금(ms)
 * @returns {string[]}
 */
export function recentChatLines(sessions, now) {
  if (!Array.isArray(sessions)) return [];
  const since = now - CHAT_DAYS * DAY_MS;
  const found = [];
  sessions.forEach((session, si) => {
    const messages = Array.isArray(session?.messages) ? session.messages : [];
    messages.forEach((m, mi) => {
      if (m?.role !== "user" || typeof m.text !== "string") return;
      const at = [m.at, m.createdAt, session.updatedAt].find((v) => typeof v === "number" && Number.isFinite(v));
      if (at === undefined || at < since) return;
      const text = m.text.trim().slice(0, CHAT_MAX_CHARS).trim();
      if (text) found.push({ text, at, si, mi });
    });
  });
  // 최신 먼저: 시각이 같으면 뒤에 한 말이 먼저(같은 대화는 메시지 순서, 다른 대화는 목록 순서)
  found.sort((a, b) => b.at - a.at || a.si - b.si || b.mi - a.mi);
  const seen = new Set();
  const lines = [];
  for (const { text } of found) {
    if (seen.has(text)) continue;
    seen.add(text);
    lines.push(text);
    if (lines.length >= CHAT_MAX_LINES) break;
  }
  return lines;
}
