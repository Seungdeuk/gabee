import { useCallback, useRef, useState } from "react";

import { getFileStatus, getRecord, sendMessage, submitDescription, updateRecord, uploadFile } from "../api";
import { formatSeconds } from "../components/ReadingStatus";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 120000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 채팅 상태와 동작을 관리한다.
 *
 * phase: idle(대기) | listening(음성 입력 중) | thinking(가비가 답을 만드는 중) | reading(올린 파일을 읽는 중)
 * 메시지: { id, role: "user" | "assistant", text, voice?, imageUri?, sources?, draft?, draftText?, doubts?, describe? }
 * describe: 글자 없는 사진의 설명 카드 { recordId, status: "pending" | "done" | "skipped" }. 메시지에 들어 있어서 대화와 함께 저장된다.
 * 읽는 중 표시는 메시지가 아니라 phase 로만 보여 줘서 서버로 보내는 대화 이력에 섞이지 않는다.
 *
 * @returns {{
 *   messages: object[],
 *   phase: "idle" | "listening" | "thinking" | "reading",
 *   readingSince: number | null,
 *   confirmDoubts: (messageId: string, edits: string[]) => Promise<void>,   // 흐린 줄 확인 카드의 결과 반영
 *   saveDescription: (messageId: string, text: string) => Promise<void>,   // 설명 카드 저장(실패하면 던진다. 카드가 오류를 보여 준다)
 *   skipDescription: (messageId: string) => void,   // 설명 카드 "나중에 할게요"
 *   send: (text: string, options?: { voice?: boolean }) => Promise<void>,
 *   sendPhoto: (file: { uri: string, name?: string, type?: string, isImage?: boolean }) => Promise<void>,   // 사진·문서 모두 올린다
 *   startListening: () => void,
 *   stopListening: () => void,
 *   editDraft: (id: string, text: string) => void,
 *   reset: () => void,
 *   load: (messages: object[]) => void,   // 저장된 대화를 불러와 이어서 쓴다
 * }}
 */
export default function useChat() {
  const [messages, setMessages] = useState([]);
  const [phase, setPhase] = useState("idle");
  const [readingSince, setReadingSince] = useState(null); // 파일 읽기를 시작한 시각(ms), 읽는 중이 아니면 null
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
    const say = (text, extra = {}) => setMessages((prev) => [...prev, { id: id(), role: "assistant", text, sources: [], ...extra }]);
    const isImage = file.isImage !== false;
    setMessages((prev) => [
      ...prev,
      isImage
        ? { id: id(), role: "user", text: "사진 올렸어요", imageUri: file.uri }
        : { id: id(), role: "user", text: `파일 올렸어요: ${file.name ?? "문서"}` },
    ]);
    const startedAt = Date.now();
    setReadingSince(startedAt);
    setPhase("reading");
    const took = () => formatSeconds((Date.now() - startedAt) / 1000);
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
        const review = result.status === "needs_review";
        const doubts = result.doubts ?? [];
        // 같은 파일에 설명 카드가 이미 있으면 또 만들지 않는다
        const needsDescription =
          result.needs_description === true && !messagesRef.current.some((m) => m.describe?.recordId === fileId);
        say(
          `${head}${detail ? `\n${detail}` : ""}\n${review ? "원본과 비교해서 맞는지 확인해 주세요." : "이어서 궁금한 걸 물어보세요."}\n(걸린 시간 ${took()})`,
          {
            ...(doubts.length > 0 ? { doubts: { recordId: fileId, lines: doubts, done: false } } : review ? { reviewId: fileId } : {}),
            ...(needsDescription ? { describe: { recordId: fileId, status: "pending" } } : {}),
          },
        );
      }
    } catch (e) {
      if (runId.current === myRun) say(e?.message || "사진을 올리지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      if (runId.current === myRun) {
        setPhase("idle");
        setReadingSince(null);
      }
    }
  }, []);

  /**
   * 채팅 카드에서 흐린 줄을 확인한 결과를 기록에 반영한다. 고친 줄이 없으면 확인만 한다.
   * @param {string} messageId 카드가 붙은 메시지
   * @param {string[]} edits 줄마다 사용자가 확인한(고친) 글
   */
  const confirmDoubts = useCallback(async (messageId, edits) => {
    const card = messagesRef.current.find((m) => m.id === messageId)?.doubts;
    if (!card) return;
    try {
      const changed = card.lines.some((line, i) => edits[i] !== line);
      if (changed) {
        let body = (await getRecord(card.recordId)).body_md;
        card.lines.forEach((line, i) => {
          if (edits[i] !== line) body = body.replace(`${line} [불확실]`, edits[i]);
        });
        await updateRecord(card.recordId, { body_md: body });
      } else {
        await updateRecord(card.recordId, {});
      }
      setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, doubts: { ...card, done: true } } : m)));
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { id: id(), role: "assistant", text: e?.message || "저장하지 못했어요. 잠시 후 다시 시도해 주세요.", sources: [] },
      ]);
    }
  }, []);

  /** 설명 카드의 글을 서버에 저장한다. 실패하면 던져서 카드 안에 오류가 보이게 한다. */
  const saveDescription = useCallback(async (messageId, text) => {
    const card = messagesRef.current.find((m) => m.id === messageId)?.describe;
    if (!card) return;
    await submitDescription(card.recordId, text);
    setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, describe: { ...card, status: "done" } } : m)));
  }, []);

  const skipDescription = useCallback((messageId) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId && m.describe ? { ...m, describe: { ...m.describe, status: "skipped" } } : m)),
    );
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

  /** 저장된 대화로 바꾼다. 진행 중이던 파일 확인은 멈춘다. */
  const load = useCallback((saved) => {
    runId.current += 1;
    nextId.current = saved.reduce((max, m) => Math.max(max, Number(m.id) + 1 || 0), nextId.current);
    setMessages(saved);
    setPhase("idle");
  }, []);

  return { messages, phase, readingSince, confirmDoubts, saveDescription, skipDescription, send, sendPhoto, startListening, stopListening, editDraft, reset, load };
}
