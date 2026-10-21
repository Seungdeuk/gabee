import { useCallback, useRef, useState } from "react";

import { sendMessage } from "../api";

/**
 * 채팅 상태와 동작을 관리한다.
 *
 * phase: idle(대기) | listening(음성 입력 중) | thinking(가비가 답을 만드는 중)
 * 메시지: { id, role: "user" | "assistant", text, voice?, sources?, draft?, draftText? }
 *
 * @returns {{
 *   messages: object[],
 *   phase: "idle" | "listening" | "thinking",
 *   send: (text: string, options?: { voice?: boolean }) => Promise<void>,
 *   startListening: () => void,
 *   stopListening: () => void,
 *   editDraft: (id: string, text: string) => void,
 *   reset: () => void,
 * }}
 */
export default function useChat() {
  const [messages, setMessages] = useState([]);
  const [phase, setPhase] = useState("idle");
  const nextId = useRef(0);
  const id = () => String(nextId.current++);

  const send = useCallback(async (text, { voice = false } = {}) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    setMessages((prev) => [...prev, { id: id(), role: "user", text: trimmed, voice }]);
    setPhase("thinking");
    try {
      const { reply, sources = [], draft = null } = await sendMessage(trimmed);
      setMessages((prev) => [
        ...prev,
        { id: id(), role: "assistant", text: reply, sources, draft, draftText: draft?.text },
      ]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { id: id(), role: "assistant", text: e?.message || "답변을 가져오지 못했어요. 잠시 후 다시 시도해 주세요.", sources: [] },
      ]);
    } finally {
      setPhase("idle");
    }
  }, []);

  const startListening = useCallback(() => setPhase("listening"), []);
  const stopListening = useCallback(() => setPhase((p) => (p === "listening" ? "idle" : p)), []);

  /** 초안 문구를 고친다(고친 문구가 보내기에 쓰인다). */
  const editDraft = useCallback((messageId, text) => {
    setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, draftText: text } : m)));
  }, []);

  const reset = useCallback(() => {
    setMessages([]);
    setPhase("idle");
  }, []);

  return { messages, phase, send, startListening, stopListening, editDraft, reset };
}
