import { useCallback, useEffect, useRef, useState } from "react";
import { InteractionManager } from "react-native";

import { listScheduleEvents } from "./api";
import { SHARE_LOAD_ERROR, buildShareEventItems, recentShareMonths, scheduleAfterSheetClose, shareConfirmCopy } from "./shareUtils";
import { dateKey } from "./togetherUtils";

const IDLE = { kind: null, status: "idle", items: [], error: "", sheetOpen: false };

/**
 * 채팅방 공유 카드 보내기의 화면 상태: "+" 메뉴에서 일정·정산을 고르면 공유 시트(항목 고르기) → 항목을 누르면 확인창 → 확인하면 전송.
 * 창(Modal)은 한 번에 하나만 뜬다: 항목을 고르면 시트를 먼저 닫고 닫힌 뒤에 확인창을, 확인창에서 취소하면 확인창을 닫고 닫힌 뒤에 시트를 다시 연다(겹쳐 뜨면 iOS 에서 열리지 않는 경우가 있다).
 * 시트·확인창을 닫아도 종류·항목·문구는 비우지 않아 닫히는 동안 제목이 비지 않는다(다음에 열 때 새로 채운다).
 * 일정 항목은 일정 탭의 내 일정(listScheduleEvents)에서 오늘 이후의 것만, 정산 항목은 이번 달부터 최근 몇 달(앱이 만든다, 금액은 앱이 계산하지 않는다).
 * 전송(send)은 useChatMessages 의 sendShare 다: 확인하면 확인창을 닫고 보내므로 실패 문구는 입력줄 위 안내에 보인다. 일정 제목·금액은 어디에도 기록하지 않는다.
 * @param {{ send: (card: { kind: "event" | "settlement", ref: string }) => Promise<boolean>, onSent?: () => void }} options 전송 성공 뒤 onSent(맨 아래로 스크롤 등)
 * @returns {{ visible: boolean, confirmVisible: boolean, kind: "event" | "settlement" | null, status: "idle" | "loading" | "ready" | "error", items: object[], error: string, pending: object | null, confirmCopy: { title: string, message: string, confirmLabel: string } | null, open: (kind: "event" | "settlement") => void, retry: () => void, close: () => void, pick: (item: object) => void, cancelPending: () => void, confirm: () => Promise<void> }}
 */
export default function useChatShare({ send, onSent }) {
  const [state, setState] = useState(IDLE);
  const [pending, setPending] = useState(null); // 마지막으로 고른 항목(확인창 문구용, 닫혀도 남긴다)
  const [confirmOpen, setConfirmOpen] = useState(false);
  const token = useRef(0); // 시트를 닫거나 다시 열면 이전 목록 응답은 버린다
  const alive = useRef(true);
  const confirming = useRef(false); // 확인을 두 번 눌러도 한 번만 보낸다(state 는 한 박자 늦다)
  const handoff = useRef(null); // 창을 닫은 뒤 다음 창을 열도록 예약한 일의 취소 함수
  const cancelHandoff = useCallback(() => {
    handoff.current?.();
    handoff.current = null;
  }, []);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      handoff.current?.();
    };
  }, []);

  /** 지금 창이 닫힌 뒤에 다음 창을 연다. */
  const after = useCallback(
    (next) => {
      cancelHandoff();
      handoff.current = scheduleAfterSheetClose(
        () => {
          handoff.current = null;
          if (alive.current) next();
        },
        { runAfterInteractions: (cb) => InteractionManager.runAfterInteractions(cb) },
      );
    },
    [cancelHandoff],
  );

  /** 시트를 연다: 정산은 바로 달 목록, 일정은 서버에서 내 일정을 받아 온다. */
  const open = useCallback(
    (kind) => {
      cancelHandoff();
      token.current += 1;
      const mine = token.current;
      setPending(null);
      setConfirmOpen(false);
      if (kind === "settlement") {
        setState({ kind, status: "ready", items: recentShareMonths(), error: "", sheetOpen: true });
        return;
      }
      setState({ kind, status: "loading", items: [], error: "", sheetOpen: true });
      listScheduleEvents()
        .then((rows) => {
          if (alive.current && token.current === mine) setState({ kind, status: "ready", items: buildShareEventItems(rows, dateKey(new Date())), error: "", sheetOpen: true });
        })
        .catch(() => {
          if (alive.current && token.current === mine) setState({ kind, status: "error", items: [], error: SHARE_LOAD_ERROR, sheetOpen: true });
        });
    },
    [cancelHandoff],
  );

  /** 시트만 닫는다(내용은 남겨 닫히는 동안 제목이 비지 않게). 목록 응답이 늦게 와도 반영하지 않는다. */
  const close = useCallback(() => {
    cancelHandoff();
    token.current += 1;
    setConfirmOpen(false);
    setState((prev) => ({ ...prev, sheetOpen: false }));
  }, [cancelHandoff]);

  /** 항목을 고르면 시트를 닫고, 닫힌 뒤에 확인창을 연다. */
  const pick = useCallback(
    (item) => {
      setPending(item);
      setState((prev) => ({ ...prev, sheetOpen: false }));
      after(() => setConfirmOpen(true));
    },
    [after],
  );

  /** 확인창에서 취소하면 확인창을 닫고, 닫힌 뒤에 시트를 다시 연다(목록은 그대로). */
  const cancelPending = useCallback(() => {
    setConfirmOpen(false);
    after(() => setState((prev) => (prev.kind ? { ...prev, sheetOpen: true } : prev)));
  }, [after]);

  const retry = useCallback(() => {
    if (state.kind) open(state.kind);
  }, [open, state.kind]);

  /** 확인: 확인창을 닫고 보낸다. 보냈으면 onSent. */
  const confirm = useCallback(async () => {
    if (!pending || !state.kind || !confirmOpen || confirming.current) return;
    confirming.current = true;
    const card = { kind: state.kind, ref: pending.ref };
    cancelHandoff();
    token.current += 1;
    setConfirmOpen(false);
    try {
      if ((await send(card)) && alive.current) onSent?.();
    } finally {
      confirming.current = false;
    }
  }, [cancelHandoff, confirmOpen, onSent, pending, send, state.kind]);

  return {
    visible: state.sheetOpen,
    confirmVisible: confirmOpen,
    kind: state.kind,
    status: state.status,
    items: state.items,
    error: state.error,
    pending,
    confirmCopy: pending && state.kind ? shareConfirmCopy(state.kind, pending) : null,
    open,
    retry,
    close,
    pick,
    cancelPending,
    confirm,
  };
}
