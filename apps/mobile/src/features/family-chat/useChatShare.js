import { useCallback, useEffect, useRef, useState } from "react";

import { listScheduleEvents } from "./api";
import { SHARE_LOAD_ERROR, buildShareEventItems, recentShareMonths, shareConfirmCopy } from "./shareUtils";
import { dateKey } from "./togetherUtils";

const IDLE = { kind: null, status: "idle", items: [], error: "" };

/**
 * 채팅방 공유 카드 보내기의 화면 상태: "+" 메뉴에서 일정·정산을 고르면 공유 시트(항목 고르기) → 항목을 누르면 확인창 → 확인하면 전송.
 * 일정 항목은 일정 탭의 내 일정(listScheduleEvents)에서 오늘 이후의 것만, 정산 항목은 이번 달부터 최근 몇 달(앱이 만든다, 금액은 앱이 계산하지 않는다).
 * 전송(send)은 useChatMessages 의 sendShare 다: 확인하면 시트·확인창을 먼저 닫고 보내므로 실패 문구는 입력줄 위 안내에 보인다. 일정 제목·금액은 어디에도 기록하지 않는다.
 * @param {{ send: (card: { kind: "event" | "settlement", ref: string }) => Promise<boolean>, onSent?: () => void }} options 전송 성공 뒤 onSent(맨 아래로 스크롤 등)
 * @returns {{ visible: boolean, kind: "event" | "settlement" | null, status: "idle" | "loading" | "ready" | "error", items: object[], error: string, pending: object | null, confirmCopy: { title: string, message: string, confirmLabel: string } | null, open: (kind: "event" | "settlement") => void, retry: () => void, close: () => void, pick: (item: object) => void, cancelPending: () => void, confirm: () => Promise<void> }}
 */
export default function useChatShare({ send, onSent }) {
  const [state, setState] = useState(IDLE);
  const [pending, setPending] = useState(null);
  const token = useRef(0); // 시트를 닫거나 다시 열면 이전 목록 응답은 버린다
  const alive = useRef(true);
  const confirming = useRef(false); // 확인을 두 번 눌러도 한 번만 보낸다(state 는 한 박자 늦다)
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  /** 시트를 연다: 정산은 바로 달 목록, 일정은 서버에서 내 일정을 받아 온다. */
  const open = useCallback((kind) => {
    token.current += 1;
    const mine = token.current;
    setPending(null);
    if (kind === "settlement") {
      setState({ kind, status: "ready", items: recentShareMonths(), error: "" });
      return;
    }
    setState({ kind, status: "loading", items: [], error: "" });
    listScheduleEvents()
      .then((rows) => {
        if (alive.current && token.current === mine) setState({ kind, status: "ready", items: buildShareEventItems(rows, dateKey(new Date())), error: "" });
      })
      .catch(() => {
        if (alive.current && token.current === mine) setState({ kind, status: "error", items: [], error: SHARE_LOAD_ERROR });
      });
  }, []);

  const close = useCallback(() => {
    token.current += 1;
    setPending(null);
    setState(IDLE);
  }, []);

  const cancelPending = useCallback(() => setPending(null), []);

  const retry = useCallback(() => {
    if (state.kind) open(state.kind);
  }, [open, state.kind]);

  /** 확인: 시트·확인창을 닫고 보낸다. 보냈으면 onSent. */
  const confirm = useCallback(async () => {
    if (!pending || !state.kind || confirming.current) return;
    confirming.current = true;
    const card = { kind: state.kind, ref: pending.ref };
    close();
    try {
      if ((await send(card)) && alive.current) onSent?.();
    } finally {
      confirming.current = false;
    }
  }, [close, onSent, pending, send, state.kind]);

  return {
    visible: state.kind != null,
    kind: state.kind,
    status: state.status,
    items: state.items,
    error: state.error,
    pending,
    confirmCopy: pending && state.kind ? shareConfirmCopy(state.kind, pending) : null,
    open,
    retry,
    close,
    pick: setPending,
    cancelPending,
    confirm,
  };
}
