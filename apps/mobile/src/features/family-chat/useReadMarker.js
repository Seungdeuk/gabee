import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

import { markRead } from "./api";
import { flushTarget, lastId, shouldMarkRead } from "./chatUtils";
import { trackMarkRead } from "./pendingRead";

export const READ_DEBOUNCE_MS = 800;

/**
 * 채팅방이 보이는 동안(포커스 + 앱이 앞에 있을 때) 내 읽음 위치를 자동으로 서버에 올린다. 누르는 동작은 없다.
 * 목록의 가장 큰 서버 메시지 id 가 지금까지 올린 값보다 커졌을 때만, 약 0.8초 모았다가 한 번 보낸다.
 * 화면이 안 보이게 되거나 닫힐 때 대기 중인 값이 있으면 기다리지 않고 즉시 한 번 올린다(앱이 백그라운드로 가는 경우 포함).
 * 실패하면 조용히 두고 다음에 id 가 바뀔 때 다시 시도한다(폴링 간격과 무관). 대화 글자는 보내지 않는다.
 * @param {{ messages: object[], myId: string | null | undefined, enabled?: boolean }} options
 */
export default function useReadMarker({ messages, myId, enabled = true }) {
  const [visible, setVisible] = useState(false);
  const marked = useRef(0); // 올렸거나 서버가 이미 반영한 가장 큰 id
  const sending = useRef(0); // 지금 보내는 중인 id(같은 id 중복 호출 방지)

  useFocusEffect(
    useCallback(() => {
      setVisible(AppState.currentState !== "background");
      const sub = AppState.addEventListener("change", (next) => setVisible(next === "active"));
      return () => {
        sub.remove();
        setVisible(false);
      };
    }, []),
  );

  const target = lastId(messages);
  const mineNewest = myId ? lastId(messages.filter((m) => m.user_id === myId)) : 0;

  const targetRef = useRef(0);
  targetRef.current = target;

  /** 읽음 올리기(진행 중 호출로 등록해 소통 탭이 기다릴 수 있게 한다). */
  const send = useCallback(async (id) => {
    sending.current = id;
    try {
      await trackMarkRead(markRead(id));
      marked.current = Math.max(marked.current, id);
    } catch {
      // 조용히 넘어가고 다음 변화 때 다시 시도한다
    } finally {
      if (sending.current === id) sending.current = 0;
    }
  }, []);

  useEffect(() => {
    // 내가 보낸 메시지가 가장 최신이면 서버가 보낼 때 이미 내 읽음 위치를 올렸다
    if (mineNewest >= 1 && mineNewest >= target) marked.current = Math.max(marked.current, mineNewest);
    if (!shouldMarkRead(target, marked.current, enabled && visible)) return undefined;
    const timer = setTimeout(() => {
      if (sending.current !== target) send(target);
    }, READ_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [target, mineNewest, enabled, visible, send]);

  // 보이던 화면이 안 보이게 되거나 닫힐 때: 디바운스를 기다리지 않고 마지막으로 본 id 를 바로 올린다
  useEffect(() => {
    if (!visible) return undefined;
    return () => {
      const id = flushTarget(targetRef.current, marked.current, sending.current);
      if (id) send(id);
    };
  }, [visible, send]);
}
