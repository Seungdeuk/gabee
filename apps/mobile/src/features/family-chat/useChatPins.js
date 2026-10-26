import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { AccessibilityInfo, AppState, Platform } from "react-native";

import { listPins, pinMessage, unpinMessage } from "./api";
import { pinErrorMessage } from "./chatUtils";
import { BUSY_NOTICE, NO_PINS_NOTICE, UNPINNED_NOTICE, canPin, initialPinsState, nextPinPollDelay, failureEffect, optimisticPin, pinResultNotice, pinSettled, pinnedIdSet, pinsReducer, reloadGate } from "./pinUtils";

const NOTICE_MS = 3500;

/**
 * 채팅방의 고정 메시지(최대 2개). 방에 들어오면 불러오고, 화면이 보이고 앱이 앞에 있는 동안 30초마다(연속 실패하면 간격을 늘려 최대 2분) 조용히 다시 조회해 다른 구성원의 변경을 반영한다.
 * 별도 타이머이며 메시지 폴링(3초)과 독립이라 과거(포커스) 모드에서도 계속 돈다. 고정·해제는 먼저 화면에 반영하고 실패하면 되돌린 뒤 안내 문구를 둔다.
 * 오래된 조회 응답(내가 그 뒤에 바꾼 것이 있거나 바꾸는 중)은 버린다. 고정 내용·메시지 글자는 어디에도 기록하지 않는다. AI 를 부르지 않는다.
 * @param {{ roomId?: string | null, enabled?: boolean, me?: { id: string, name: string } | null }} options roomId 가 없으면 가족 전체방, enabled 가 false 면 아무것도 부르지 않는다
 * @returns {{ pins: object[], expanded: boolean, setExpanded: (value: boolean) => void, notice: string, say: (text: string) => void, isPinned: (messageId: number|string) => boolean, pin: (message: object) => Promise<boolean>, unpin: (messageId: number|string) => Promise<boolean>, showPins: () => void, reload: () => Promise<void> }}
 */
export default function useChatPins({ roomId = null, enabled = true, me = null }) {
  const [state, dispatch] = useReducer(pinsReducer, initialPinsState);
  const [expanded, setExpanded] = useState(true); // 기본 펼침
  const [notice, setNotice] = useState("");
  const live = useRef(initialPinsState); // reducer 와 같은 규칙을 바로 적용해 두는 최신 상태(렌더를 기다리지 않고 읽는다)
  const gate = useRef({ inFlight: false, again: false });
  const apply = useCallback((action) => {
    live.current = pinsReducer(live.current, action);
    dispatch(action);
  }, []);
  const seq = useRef(0);
  const pending = useRef(0); // 고정·해제 요청 중인 수(그동안 조회 응답은 버린다)
  const busy = useRef(new Set()); // 같은 메시지를 연타해도 한 번만 보낸다
  const failures = useRef(0);
  const timer = useRef(null);
  const running = useRef(false);
  const generation = useRef(0);
  const alive = useRef(true);
  const noticeTimer = useRef(null);
  const meRef = useRef(me);
  meRef.current = me;
  const roomRef = useRef(roomId);
  roomRef.current = roomId;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      clearTimeout(noticeTimer.current);
    };
  }, []);

  const say = useCallback((text) => {
    if (!alive.current) return;
    setNotice(text);
    clearTimeout(noticeTimer.current);
    if (text && Platform.OS === "ios") AccessibilityInfo.announceForAccessibility(text); // iOS 는 liveRegion 이 없어 읽어 주기를 따로 한다
    if (text) noticeTimer.current = setTimeout(() => alive.current && setNotice(""), NOTICE_MS);
  }, []);

  /** 목록을 한 번 조회한다. 조회 중이면 끝난 뒤 한 번 더 한다(서버 맞춤이 빠지지 않게). 실패는 조용히 센다(고정 바만 그대로 둔다). */
  const reload = useCallback(async () => {
    if (pending.current > 0) return;
    const asked = reloadGate(gate.current, "request");
    gate.current = asked.gate;
    if (!asked.run) return;
    seq.current += 1;
    const mine = seq.current;
    try {
      const res = await listPins({ roomId: roomRef.current });
      failures.current = 0;
      if (pinSettled({ pending: pending.current, alive: alive.current })) apply({ type: "loaded", seq: mine, items: res?.items });
    } catch {
      failures.current += 1;
    } finally {
      const done = reloadGate(gate.current, "done");
      gate.current = done.gate;
      if (done.run && alive.current) reload();
    }
  }, [apply]);

  const stop = useCallback(() => {
    running.current = false;
    clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const start = useCallback(() => {
    if (running.current) return;
    running.current = true;
    generation.current += 1;
    const mine = generation.current; // 멈췄다 다시 켜졌을 때 이전 반복이 남아 두 개가 돌지 않게 한다
    const tick = async () => {
      await reload();
      if (!running.current || !alive.current || generation.current !== mine) return;
      timer.current = setTimeout(tick, nextPinPollDelay(failures.current));
    };
    tick();
  }, [reload]);

  useFocusEffect(
    useCallback(() => {
      if (!enabled) return undefined;
      if (AppState.currentState !== "background") start();
      const sub = AppState.addEventListener("change", (next) => {
        if (next === "active") start();
        else stop();
      });
      return () => {
        sub.remove();
        stop();
      };
    }, [enabled, start, stop]),
  );

  /**
   * 요청을 보내기 전에 미리 반영하고, 실패하면 그 동작만 거꾸로 적용한다(다른 요청이 바꾼 항목은 그대로).
   * 같은 메시지에 요청이 진행 중이면 "처리 중이에요" 안내만 하고 보내지 않는다.
   * @param {{ messageId: number, optimistic: object | null, revert: object | null, request: () => Promise<object | null>, action: "pin" | "unpin" }} args optimistic·revert 가 null 이면 화면은 바꾸지 않는다
   * @returns {Promise<boolean>}
   */
  const mutate = useCallback(
    async ({ messageId, optimistic, revert, request, action }) => {
      const key = Number(messageId);
      if (busy.current.has(key)) {
        say(BUSY_NOTICE);
        return false;
      }
      busy.current.add(key);
      pending.current += 1;
      seq.current += 1;
      if (optimistic) apply({ ...optimistic, seq: seq.current });
      try {
        const result = await request();
        seq.current += 1;
        if (action === "pin") {
          apply({ type: "confirmed", seq: seq.current, result });
          say(pinResultNotice(result));
        } else {
          say(UNPINNED_NOTICE);
        }
        return true;
      } catch (e) {
        seq.current += 1;
        if (failureEffect(action, e) === "keep") {
          say(pinErrorMessage(e, action)); // 이미 풀려 있으면 목록에서 빠진 채로 둔다
          return false;
        }
        if (revert) apply({ ...revert, seq: seq.current });
        say(pinErrorMessage(e, action));
        return false;
      } finally {
        busy.current.delete(key);
        pending.current -= 1;
        if (pinSettled({ pending: pending.current, alive: alive.current })) reload(); // 서버 기준으로 한 번 맞춘다
      }
    },
    [apply, reload, say],
  );

  const pin = useCallback(
    async (message) => {
      if (!canPin(message)) return false;
      const messageId = Number(message.id);
      const cur = live.current.items;
      const already = cur.some((p) => p.message_id === messageId);
      const { replacedId } = optimisticPin(cur, message, meRef.current, new Date().toISOString());
      const restore = replacedId != null ? (cur.find((p) => p.message_id === replacedId) ?? null) : null;
      return mutate({
        messageId,
        optimistic: already ? null : { type: "pin", message, me: meRef.current, now: new Date().toISOString() },
        revert: already ? null : { type: "revert_pin", messageId, restore },
        request: () => pinMessage({ roomId: roomRef.current, messageId }),
        action: "pin",
      });
    },
    [mutate],
  );

  const unpin = useCallback(
    (messageId) => {
      const id = Number(messageId);
      const item = live.current.items.find((p) => p.message_id === id);
      return mutate({
        messageId: id,
        optimistic: item ? { type: "unpin", messageId: id } : null,
        revert: item ? { type: "revert_unpin", item } : null,
        request: () => unpinMessage({ roomId: roomRef.current, messageId: id }),
        action: "unpin",
      });
    },
    [mutate],
  );

  /** 서랍의 "고정 메시지": 고정 바를 펼쳐 보여 준다(고정이 없으면 안내만). */
  const showPins = useCallback(() => {
    if (live.current.items.length === 0) {
      say(NO_PINS_NOTICE);
      return;
    }
    setExpanded(true);
  }, [say]);

  const isPinned = useCallback((messageId) => pinnedIdSet(state.items).has(Number(messageId)), [state.items]);

  return { pins: state.items, expanded, setExpanded, notice, say, isPinned, pin, unpin, showPins, reload };
}
