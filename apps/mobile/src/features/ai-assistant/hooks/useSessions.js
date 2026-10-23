import { useCallback, useEffect, useRef, useState } from "react";

import { deleteSession, loadSessions, saveSession } from "../storage/chatStore";

const SAVE_DELAY_MS = 500;

const newId = () => `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/** 첫 질문을 대화 제목으로 쓴다. 사진만 올렸다면 그 안내 문구가 제목이 된다. */
function titleOf(messages) {
  const first = messages.find((m) => m.role === "user");
  const text = (first?.text ?? "새 대화").replace(/\s+/g, " ").trim();
  return text.length > 30 ? `${text.slice(0, 30)}…` : text;
}

/**
 * 대화 목록을 기기에 저장하고 불러온다.
 * 지금 대화(messages)가 바뀌면 잠깐 뒤 자동 저장하고, 목록에서 고른 대화는 chat.load 로 채팅 화면에 넣는다.
 * @param {{ messages: object[], load: (messages: object[]) => void, reset: () => void }} chat useChat 의 값
 */
export default function useSessions({ messages, load, reset }) {
  const [sessions, setSessions] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const idRef = useRef(null);
  const skipSave = useRef(false); // 목록에서 불러온 직후의 변경은 저장하지 않는다(순서가 뒤바뀌지 않게)
  const timer = useRef(null);

  useEffect(() => {
    loadSessions().then(setSessions);
  }, []);

  useEffect(() => {
    if (skipSave.current) {
      skipSave.current = false;
      return undefined;
    }
    if (messages.length === 0) return undefined;
    if (!idRef.current) {
      idRef.current = newId();
      setCurrentId(idRef.current);
    }
    const session = { id: idRef.current, title: titleOf(messages), updatedAt: Date.now(), messages };
    clearTimeout(timer.current);
    timer.current = setTimeout(() => saveSession(session).then(setSessions), SAVE_DELAY_MS);
    return () => clearTimeout(timer.current);
  }, [messages]);

  const startNew = useCallback(() => {
    idRef.current = null;
    setCurrentId(null);
    reset();
  }, [reset]);

  const open = useCallback(
    (id) => {
      const found = sessions.find((s) => s.id === id);
      if (!found || id === idRef.current) return;
      skipSave.current = true;
      idRef.current = id;
      setCurrentId(id);
      load(found.messages);
    },
    [sessions, load],
  );

  const remove = useCallback(
    async (id) => {
      setSessions(await deleteSession(id));
      if (idRef.current === id) startNew();
    },
    [startNew],
  );

  return { sessions, currentId, startNew, open, remove };
}
