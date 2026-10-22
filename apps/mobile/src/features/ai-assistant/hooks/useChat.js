import { useCallback, useRef, useState } from "react";

import { getFileStatus, sendMessage, uploadFile } from "../api";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 120000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 채팅 상태와 동작을 관리한다.
 *
 * phase: idle(대기) | listening(음성 입력 중) | thinking(가비가 답을 만드는 중) | reading(올린 파일을 읽는 중)
 * 메시지: { id, role: "user" | "assistant", text, voice?, imageUri?, sources?, draft?, draftText? }
 * 읽는 중 표시는 메시지가 아니라 phase 로만 보여 줘서 서버로 보내는 대화 이력에 섞이지 않는다.
 *
 * @returns {{
 *   messages: object[],
 *   phase: "idle" | "listening" | "thinking" | "reading",
 *   send: (text: string, options?: { voice?: boolean }) => Promise<void>,
 *   sendPhoto: (file: { uri: string, name?: string, type?: string }) => Promise<void>,
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
  const messagesRef = useRef([]);
  messagesRef.current = messages;
  const runId = useRef(0); // 새 대화로 바뀌면 진행 중이던 파일 확인을 멈추기 위한 번호
  const id = () => String(nextId.current++);

  const send = useCallback(async (text, { voice = false } = {}) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    const history = messagesRef.current.map(({ role, text: t }) => ({ role, text: t }));
    setMessages((prev) => [...prev, { id: id(), role: "user", text: trimmed, voice }]);
    setPhase("thinking");
    try {
      const { reply, sources = [], draft = null } = await sendMessage(trimmed, history);
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

  /** 사진을 올리고, 서버가 분석을 끝낼 때까지 2초 간격으로 확인한다(최대 2분). */
  const sendPhoto = useCallback(async (file) => {
    const myRun = ++runId.current;
    const say = (text) => setMessages((prev) => [...prev, { id: id(), role: "assistant", text, sources: [] }]);
    setMessages((prev) => [...prev, { id: id(), role: "user", text: "사진 올렸어요", imageUri: file.uri }]);
    setPhase("reading");
    try {
      const { id: fileId } = await uploadFile(file);
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      let result = null;
      while (Date.now() < deadline) {
        await sleep(POLL_INTERVAL_MS);
        if (runId.current !== myRun) return;
        try {
          const status = await getFileStatus(fileId);
          if (status.status !== "received") {
            result = status;
            break;
          }
        } catch (e) {
          if (e?.status !== 0) throw e; // 잠깐 끊긴 네트워크는 다음 확인에서 다시 시도한다
        }
      }
      if (runId.current !== myRun) return;
      if (!result) {
        say("분석이 오래 걸려요. 잠시 뒤 다시 확인해 보세요.");
      } else if (result.status === "failed") {
        say(`${result.message || "파일을 읽지 못했어요."} 다시 올려 주세요.`);
      } else {
        const detail = [result.kind_label && `분류: ${result.kind_label}`, result.title && `제목: ${result.title}`, result.description]
          .filter(Boolean)
          .join("\n");
        const head = result.status === "needs_review" ? "저장했지만 내용을 한 번 확인해 주세요." : "저장했어요.";
        say(`${head}${detail ? `\n${detail}` : ""}\n이어서 궁금한 걸 물어보세요.`);
      }
    } catch (e) {
      if (runId.current === myRun) say(e?.message || "사진을 올리지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      if (runId.current === myRun) setPhase("idle");
    }
  }, []);

  const startListening = useCallback(() => setPhase("listening"), []);
  const stopListening = useCallback(() => setPhase((p) => (p === "listening" ? "idle" : p)), []);

  /** 초안 문구를 고친다(고친 문구가 보내기에 쓰인다). */
  const editDraft = useCallback((messageId, text) => {
    setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, draftText: text } : m)));
  }, []);

  const reset = useCallback(() => {
    runId.current += 1;
    setMessages([]);
    setPhase("idle");
  }, []);

  return { messages, phase, send, sendPhoto, startListening, stopListening, editDraft, reset };
}
