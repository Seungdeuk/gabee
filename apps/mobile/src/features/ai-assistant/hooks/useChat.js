import { useCallback, useRef, useState } from "react";

import { sendMessage } from "../api";

/**
 * 채팅 상태와 전송 동작을 관리한다.
 * @returns {{
 *   messages: { id: string, role: "user" | "assistant", text: string }[],
 *   isTyping: boolean,
 *   send: (text: string) => Promise<void>,
 *   reset: () => void,
 * }}
 */
export default function useChat() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const nextId = useRef(0);

  const makeMessage = (role, text) => ({ id: String(nextId.current++), role, text });

  const send = useCallback(async (text) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    setMessages((prev) => [...prev, makeMessage("user", trimmed)]);
    setIsTyping(true);
    try {
      const reply = await sendMessage(trimmed);
      setMessages((prev) => [...prev, makeMessage("assistant", reply)]);
    } catch {
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", "답변을 가져오지 못했어요. 잠시 후 다시 시도해 주세요."),
      ]);
    } finally {
      setIsTyping(false);
    }
  }, []);

  const reset = useCallback(() => {
    setMessages([]);
    setIsTyping(false);
  }, []);

  return { messages, isTyping, send, reset };
}
