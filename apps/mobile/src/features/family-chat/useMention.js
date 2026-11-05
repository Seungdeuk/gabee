import { useCallback, useEffect, useRef, useState } from "react";

import { assistantErrorText } from "@/features/ai-assistant/errors";

import { askAssistantInRoom } from "./api";
import { EMPTY_QUESTION_HINT, makeNote, mentionHistory, pushThread } from "./mention";

const BUSY_HINT = "앞선 질문에 답하는 중이에요. 끝난 뒤에 다시 불러 주세요.";

/**
 * 가족 채팅방의 @가비. 메시지를 보낸 뒤 질문을 메인 AI 비서에게 넘기고, 답기다림·안내·확인 카드는 이 화면에만 보이는 항목(notes)으로 둔다.
 * - 답은 서버가 가비 이름으로 방(가족 전체방, 1:1 방이면 그 1:1 방)에 저장한다(방 사람들에게 공유, 기록으로 남는다). 앱은 다시 올리지 않고, 새 메시지 확인(3초)에 나타난다.
 * - 확인이 필요한 요청의 카드는 질문한 사람 화면에만 있고 서버에 남지 않는다. 이 화면을 닫으면 카드와 대화 이력(thread)이 사라진다.
 * - 앞 대화(thread)는 내가 @가비 로 나눈 최근 대화뿐이다. 오류가 난 질문은 이어 가지 않는다.
 * @param {string} [roomId] 1:1 방 id. 있으면 답을 그 1:1 방(두 사람)에 저장한다. 없으면 가족 전체방
 * @returns {{ notes: object[], ask: (question: string) => Promise<void>, info: (text: string) => void, dismiss: (id: string) => void, resolveCard: (noteId: string, index: number, status: string, text: string) => void }}
 */
export default function useMention(roomId) {
  const [notes, setNotes] = useState([]);
  const thread = useRef([]);
  const counter = useRef(0);
  const alive = useRef(true);
  const busy = useRef(false);

  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  const nextId = () => {
    counter.current += 1;
    return `note-${Date.now()}-${counter.current}`;
  };
  const add = useCallback((note) => setNotes((prev) => [...prev, note]), []);
  const replace = useCallback((id, note) => alive.current && setNotes((prev) => prev.map((n) => (n.id === id ? note : n))), []);
  const remove = useCallback((id) => alive.current && setNotes((prev) => prev.filter((n) => n.id !== id)), []);

  const info = useCallback((text) => add(makeNote({ id: nextId(), state: "info", text })), [add]);
  const dismiss = useCallback((id) => setNotes((prev) => prev.filter((n) => n.id !== id)), []);

  const ask = useCallback(
    async (question) => {
      const q = String(question ?? "").trim();
      if (!q) {
        info(EMPTY_QUESTION_HINT);
        return;
      }
      if (busy.current) {
        info(BUSY_HINT);
        return;
      }
      busy.current = true;
      const id = nextId();
      add(makeNote({ id, state: "pending", question: q }));
      try {
        const res = await askAssistantInRoom(q, mentionHistory(thread.current), roomId);
        const at = Date.now();
        thread.current = pushThread(thread.current, { role: "user", text: q, at }, { role: "assistant", text: res.reply, at });
        if (res.postedMessageId == null) {
          // 서버가 방에 저장하지 않은 답(구 서버): 답을 잃지 않게 이 화면에만 보여 준다
          replace(id, makeNote({ id, state: "reply", text: res.reply, question: q, confirmCards: res.confirmCards }));
        } else if (res.confirmCards.length > 0) {
          replace(id, makeNote({ id, state: "cards", question: q, confirmCards: res.confirmCards })); // 답 글은 방에 저장됐고, 확인 카드만 내 화면에 둔다
        } else {
          remove(id); // 새 메시지 확인에서 가비 말풍선으로 나타난다
        }
      } catch (e) {
        replace(id, makeNote({ id, state: "error", text: assistantErrorText(e), question: q }));
      } finally {
        busy.current = false;
      }
    },
    [add, info, remove, replace, roomId],
  );

  /** 일정 확인 카드를 처리했거나 취소했을 때: 카드를 결과 한 줄로 바꾼다(이 화면에만 있는 항목이라 저장하지 않는다). */
  const resolveCard = useCallback((noteId, index, status, text) => {
    setNotes((prev) =>
      prev.map((n) => (n.id === noteId ? { ...n, confirmCards: n.confirmCards.map((c, i) => (i === index ? { ...c, status, resultText: text } : c)) } : n)),
    );
  }, []);

  return { notes, ask, info, dismiss, resolveCard };
}
