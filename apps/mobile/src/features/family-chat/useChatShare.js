import { useCallback, useEffect, useReducer, useRef } from "react";
import { InteractionManager } from "react-native";

import { listScheduleEvents } from "./api";
import { SHARE_FLOW_IDLE, shareFlowReducer } from "./shareFlow";
import { SHARE_LOAD_ERROR, buildShareEventItems, recentShareMonths, scheduleAfterSheetClose, shareConfirmCopy } from "./shareUtils";
import { dateKey } from "./togetherUtils";

/**
 * 채팅방 공유 카드 보내기의 화면 상태: "+" 메뉴에서 일정·정산을 고르면 공유 시트(항목 고르기) → 항목을 누르면 확인창 → 확인하면 전송.
 * 상태 전이는 순수 함수 shareFlowReducer(shareFlow.js)가 정하고 이 훅은 타이머(창 넘기기)·목록 불러오기·전송만 맡는다.
 * 창(Modal)은 한 번에 하나만 뜬다: 항목을 고르면 시트를 먼저 닫고 닫힌 뒤에 확인창을, 확인창에서 취소하면 확인창을 닫고 닫힌 뒤에 시트를 다시 연다(겹쳐 뜨면 iOS 에서 열리지 않는 경우가 있다).
 * 시트·확인창을 닫아도 종류·항목·문구는 비우지 않아 닫히는 동안 제목이 비지 않는다(다음에 열 때 새로 채운다).
 * 일정 항목은 일정 탭의 내 일정(listScheduleEvents)에서 오늘 이후의 것만, 정산 항목은 이번 달부터 최근 몇 달(앱이 만든다, 금액은 앱이 계산하지 않는다).
 * 전송(send)은 useChatMessages 의 sendShare 다: 확인하면 확인창을 닫고 보내므로 실패 문구는 입력줄 위 안내에 보인다. 일정 제목·금액은 어디에도 기록하지 않는다.
 * @param {{ send: (card: { kind: "event" | "settlement", ref: string }) => Promise<boolean>, onSent?: () => void }} options 전송 성공 뒤 onSent(맨 아래로 스크롤 등)
 * @returns {{ visible: boolean, confirmVisible: boolean, kind: "event" | "settlement" | null, status: "idle" | "loading" | "ready" | "error", items: object[], error: string, pending: object | null, confirmCopy: { title: string, message: string, confirmLabel: string } | null, open: (kind: "event" | "settlement") => void, retry: () => void, close: () => void, pick: (item: object) => void, cancelPending: () => void, confirm: () => Promise<void>, cancelHandoff: () => void }}
 */
export default function useChatShare({ send, onSent }) {
  const [state, dispatch] = useReducer(shareFlowReducer, SHARE_FLOW_IDLE);
  const tokenRef = useRef(0); // 목록 요청 번호(reducer 가 같은 번호의 응답만 반영한다)
  const alive = useRef(true);
  const confirming = useRef(false); // 확인을 두 번 눌러도 한 번만 보낸다(state 는 한 박자 늦다)
  const handoff = useRef(null); // 창을 닫은 뒤 다음 창을 열도록 예약한 일의 취소 함수
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      handoff.current?.();
    };
  }, []);

  /**
   * 예약해 둔 "다음 창 열기"를 취소한다(다른 창이 먼저 열릴 때 겹치지 않게).
   * @returns {void}
   */
  const cancelHandoff = useCallback(() => {
    handoff.current?.();
    handoff.current = null;
  }, []);

  /**
   * 지금 창이 닫힌 뒤(상호작용 완료 + 지연)에 다음 창을 연다. 이전 예약은 취소한다.
   * @param {() => void} next 닫힘이 끝난 뒤 실행할 일
   * @returns {void}
   */
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

  /**
   * 시트를 연다: 정산은 바로 달 목록, 일정은 서버에서 내 일정을 받아 온다(늦게 온 이전 응답은 버린다).
   * @param {"event" | "settlement"} kind
   * @returns {void}
   */
  const open = useCallback(
    (kind) => {
      cancelHandoff();
      tokenRef.current += 1;
      const token = tokenRef.current;
      if (kind === "settlement") {
        dispatch({ type: "open", kind, token, items: recentShareMonths() });
        return;
      }
      dispatch({ type: "open", kind, token });
      listScheduleEvents()
        .then((rows) => alive.current && dispatch({ type: "loaded", token, items: buildShareEventItems(rows, dateKey(new Date())) }))
        .catch(() => alive.current && dispatch({ type: "failed", token, error: SHARE_LOAD_ERROR }));
    },
    [cancelHandoff],
  );

  /**
   * 시트만 닫는다(내용은 남겨 닫히는 동안 제목이 비지 않게). 목록 응답이 늦게 와도 반영하지 않는다.
   * @returns {void}
   */
  const close = useCallback(() => {
    cancelHandoff();
    dispatch({ type: "close" });
  }, [cancelHandoff]);

  /**
   * 항목을 고르면 시트를 닫고, 닫힌 뒤에 확인창을 연다.
   * @param {object} item 시트 항목({ ref, title, line, badge })
   * @returns {void}
   */
  const pick = useCallback(
    (item) => {
      dispatch({ type: "pick", item });
      after(() => dispatch({ type: "showConfirm" }));
    },
    [after],
  );

  /**
   * 확인창에서 취소하면 확인창을 닫고, 닫힌 뒤에 시트를 다시 연다(목록은 그대로). 확인창이 열려 있지 않거나 보내는 중이면 무시한다.
   * @returns {void}
   */
  const cancelPending = useCallback(() => {
    if (!state.confirmOpen || confirming.current) return;
    dispatch({ type: "cancelPending" });
    after(() => dispatch({ type: "reopenSheet" }));
  }, [after, state.confirmOpen]);

  /**
   * 목록을 다시 불러온다(오류의 "다시 시도").
   * @returns {void}
   */
  const retry = useCallback(() => {
    if (state.kind) open(state.kind);
  }, [open, state.kind]);

  /**
   * 확인: 확인창을 닫고 보낸다. 보냈으면 onSent. 확인창이 열려 있지 않거나 이미 보내는 중이면 무시한다.
   * @returns {Promise<void>}
   */
  const confirm = useCallback(async () => {
    if (!state.pending || !state.kind || !state.confirmOpen || confirming.current) return;
    confirming.current = true;
    const card = { kind: state.kind, ref: state.pending.ref };
    cancelHandoff();
    dispatch({ type: "confirm" });
    try {
      if ((await send(card)) && alive.current) onSent?.();
    } finally {
      confirming.current = false;
    }
  }, [cancelHandoff, onSent, send, state.confirmOpen, state.kind, state.pending]);

  return {
    visible: state.sheetOpen,
    confirmVisible: state.confirmOpen,
    kind: state.kind,
    status: state.status,
    items: state.items,
    error: state.error,
    pending: state.pending,
    confirmCopy: state.pending && state.kind ? shareConfirmCopy(state.kind, state.pending) : null,
    open,
    retry,
    close,
    pick,
    cancelPending,
    confirm,
    cancelHandoff,
  };
}
