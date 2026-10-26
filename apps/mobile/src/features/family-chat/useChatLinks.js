import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { AccessibilityInfo, AppState, Platform } from "react-native";

import { createLink, deleteLink, listLinks } from "./api";
import { linkErrorMessage } from "./chatUtils";
import {
  BUSY_NOTICE,
  LINKS_LIMIT,
  REMOVED_NOTICE,
  canReloadLinks,
  deleteFailureEffect,
  badgesFor,
  initialLinksState,
  linkInputFromCandidate,
  linkKey,
  linkReloadGate,
  linkSettled,
  linksByMessage,
  linksReducer,
  nextLinkPollDelay,
  optimisticLink,
  runGuarded,
  tryBegin,
} from "./linkUtils";

const NOTICE_MS = 3500;

/**
 * 채팅방에서 등록한 일정·할 일과 원본 메시지의 연결. 방에 들어오면 불러오고(최근 100), 화면이 보이고 앱이 앞에 있는 동안 30초마다(연속 실패하면 간격을 늘려 최대 2분) 조용히 다시 조회한다.
 * 등록은 먼저 화면에 반영하고 서버 응답으로 바꾼다. 연결 저장은 부가 기능이라 실패해도 안내 없이 그 항목만 되돌린다(등록 자체에는 영향이 없다).
 * 삭제(만든 사람만)는 먼저 화면에서 빼고 실패하면 그 항목만 되살린 뒤 안내 문구를 둔다. 오래된 조회 응답(내가 그 뒤에 바꿨거나 바꾸는 중)은 버린다.
 * 제목·메시지 글자는 어디에도 기록하지 않는다. AI 를 부르지 않는다.
 * @param {{ roomId?: string | null, enabled?: boolean, me?: { id: string, name: string } | null, findMessage?: (messageId: number) => ({ text?: string, user_name?: string } | null | undefined), poll?: boolean }} options roomId 가 없으면 가족 전체방, enabled 가 false 면 아무것도 부르지 않는다, poll 이 false 면(1:1 방) 처음 한 번만 조회하고 이후는 refresh 로만 조회한다
 * @returns {{ links: object[], status: "loading" | "ready" | "error", byMessage: Map<number, object[]>, badgesOf: (messageId: number|string) => { kind: string, label: string }[], notice: string, say: (text: string) => void, registerCandidate: (args: { kind: "event" | "todo", targetId: unknown, candidate: object }) => Promise<boolean>, remove: (link: object) => Promise<boolean>, reload: () => Promise<void>, refresh: () => Promise<void> }}
 */
export default function useChatLinks({ roomId = null, enabled = true, me = null, findMessage, poll = true }) {
  const [state, dispatch] = useReducer(linksReducer, initialLinksState);
  const [status, setStatus] = useState("loading");
  const [notice, setNotice] = useState("");
  const live = useRef(initialLinksState); // reducer 와 같은 규칙을 바로 적용해 두는 최신 상태
  const gate = useRef({ inFlight: false, again: false });
  const apply = useCallback((action) => {
    live.current = linksReducer(live.current, action);
    dispatch(action);
  }, []);
  const seq = useRef(0);
  const pending = useRef(0); // 등록·삭제 요청 중인 수(그동안 조회 응답은 버린다)
  const busy = useRef(new Set());
  const tempCount = useRef(0);
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
  const pollRef = useRef(poll);
  pollRef.current = poll;
  const findRef = useRef(findMessage);
  findRef.current = findMessage;

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
    if (text && Platform.OS === "ios") AccessibilityInfo.announceForAccessibility(text);
    if (text) noticeTimer.current = setTimeout(() => alive.current && setNotice(""), NOTICE_MS);
  }, []);

  /** 목록을 한 번 조회한다. 조회 중이면 끝난 뒤 한 번 더 한다. 첫 조회가 실패하면 status 가 error, 이후 실패는 조용히 센다. */
  const reload = useCallback(async () => {
    if (!canReloadLinks(pending.current)) return;
    const asked = linkReloadGate(gate.current, "request");
    gate.current = asked.gate;
    if (!asked.run) return;
    seq.current += 1;
    const mine = seq.current;
    try {
      const res = await listLinks({ roomId: roomRef.current, limit: LINKS_LIMIT });
      failures.current = 0;
      if (linkSettled({ pending: pending.current, alive: alive.current })) {
        apply({ type: "loaded", seq: mine, items: res?.items });
        setStatus("ready");
      }
    } catch {
      failures.current += 1;
      if (alive.current) setStatus((s) => (s === "ready" ? s : "error"));
    } finally {
      const done = linkReloadGate(gate.current, "done");
      gate.current = done.gate;
      if (done.run && alive.current) reload();
    }
  }, [apply]);

  const retry = useCallback(async () => {
    setStatus("loading");
    await reload();
  }, [reload]);

  const stop = useCallback(() => {
    running.current = false;
    clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const start = useCallback(() => {
    if (running.current) return;
    running.current = true;
    generation.current += 1;
    const mine = generation.current;
    const tick = async () => {
      await reload();
      if (!running.current || !alive.current || generation.current !== mine) return;
      const delay = nextLinkPollDelay(failures.current, pollRef.current);
      if (delay == null) return; // 반복하지 않는 방(1:1)
      timer.current = setTimeout(tick, delay);
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
   * 등록한 AI 후보를 원본 메시지에 연결한다. 원본(source_message_ids 첫 번째)·등록 id 가 없으면 아무것도 하지 않는다.
   * 서버 저장이 실패하면 미리 그린 항목만 조용히 뺀다(등록 흐름을 막지 않는다). 절대 던지지 않는다.
   * @param {{ kind: "event" | "todo", targetId: unknown, candidate: object }} args
   * @returns {Promise<boolean>} 연결이 저장됐는지
   */
  const registerCandidate = useCallback(
    async ({ kind, targetId, candidate }) => {
      let input = null;
      try {
        input = linkInputFromCandidate({ kind, targetId, candidate });
      } catch {
        return false;
      }
      if (!input) return false;
      const key = linkKey(input);
      if (!tryBegin(busy.current, key)) return false;
      pending.current += 1;
      let added = null;
      return runGuarded({
        work: async () => {
          seq.current += 1;
          tempCount.current += 1;
          added = optimisticLink(live.current.items, input, meRef.current, findRef.current?.(input.messageId) ?? null, {
            nowIso: new Date().toISOString(),
            tempId: `tmp:${Date.now()}-${tempCount.current}`,
            roomId: roomRef.current,
          }).added;
          if (added) apply({ type: "add", seq: seq.current, item: added });
          const item = await createLink({ roomId: roomRef.current, ...input });
          seq.current += 1;
          apply({ type: "confirmed", seq: seq.current, tempId: added ? added.id : "", item });
          return true;
        },
        onError: () => {
          seq.current += 1;
          if (added) apply({ type: "revert_add", seq: seq.current, tempId: added.id });
        },
        leave: () => {
          busy.current.delete(key);
          pending.current -= 1;
          if (linkSettled({ pending: pending.current, alive: alive.current })) reload().catch(() => {}); // 서버 기준으로 한 번 맞춘다
        },
      });
    },
    [apply, reload],
  );

  /**
   * 연결을 지운다(만든 사람만 서버가 허용). 먼저 화면에서 빼고, 실패하면 그 항목만 되살리고 안내한다. 404 는 이미 없는 것이라 뺀 채로 둔다.
   * @param {{ id: string }} link
   * @returns {Promise<boolean>}
   */
  const remove = useCallback(
    async (link) => {
      const item = live.current.items.find((l) => l.id === link?.id);
      if (!item) return false;
      const key = `del:${item.id}`;
      if (busy.current.has(key)) {
        say(BUSY_NOTICE);
        return false;
      }
      busy.current.add(key);
      pending.current += 1;
      seq.current += 1;
      apply({ type: "remove", seq: seq.current, linkId: item.id });
      try {
        await deleteLink({ roomId: roomRef.current, linkId: item.id });
        seq.current += 1;
        say(REMOVED_NOTICE);
        return true;
      } catch (e) {
        seq.current += 1;
        if (deleteFailureEffect(e) === "revert") apply({ type: "revert_remove", seq: seq.current, item });
        say(linkErrorMessage(e, "delete"));
        return false;
      } finally {
        busy.current.delete(key);
        pending.current -= 1;
        if (linkSettled({ pending: pending.current, alive: alive.current })) reload();
      }
    },
    [apply, reload, say],
  );

  const byMessage = useMemo(() => linksByMessage(state.items), [state.items]);
  const badgesOf = useCallback((messageId) => badgesFor(byMessage.get(Number(messageId))), [byMessage]);

  return { links: state.items, status, byMessage, badgesOf, notice, say, registerCandidate, remove, reload: retry, refresh: reload };
}
