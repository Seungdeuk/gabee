import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

import { getReadStates, getRoomInfo, listMessages, sendMessage } from "./api";
import { canSend, firstId, isNoGroup, lastId, mergeMessages, nextPollDelay, readStatesDue, roomErrorMessage, trimDraft } from "./chatUtils";

const FIRST_PAGE = 50;
const POLL_PAGE = 100;

/**
 * 내 가족(채팅방) 정보. 그룹이 없으면 status 가 "none".
 * @returns {{ status: "loading" | "none" | "ready" | "error", room: object | null, me: { id: string, name: string } | null, error: string, reload: () => Promise<void> }}
 */
export function useRoomInfo() {
  const [state, setState] = useState({ status: "loading", room: null, me: null, error: "" });
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    try {
      const room = await getRoomInfo();
      const mine = room.members?.find((m) => m.id === room.my_id);
      const me = room.my_id ? { id: room.my_id, name: mine?.display_name || mine?.name || "나" } : null;
      if (alive.current) setState({ status: "ready", room, me, error: "" });
    } catch (e) {
      if (!alive.current) return;
      if (isNoGroup(e)) setState({ status: "none", room: null, me: null, error: "" });
      else setState({ status: "error", room: null, me: null, error: roomErrorMessage(e) });
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload]),
  );
  return { ...state, reload };
}

/**
 * 채팅 메시지 목록. 처음엔 최근 50개, 이후 화면이 보이는 동안 3초마다 조용히 새 메시지만 확인한다.
 * 같은 3초 틱에서 구성원별 읽음 위치(readStates)도 함께 조회한다(별도 타이머 없음). 메시지 조회 오류만 확인 간격을 늘린다(최대 30초).
 * 읽음 조회는 실패하면 자체 횟수에 따라 틱을 건너뛰며 재시도하고(2^n 틱, 최대 10틱), 404 면 이 세션 동안 끈다. 한 번도 못 받았거나 실패 중이면 readStates 는 null 이라 숫자를 표시하지 않는다.
 * 메시지 전송·확인·읽음 조회는 AI 를 부르지 않는다.
 * @param {{ me: { id: string, name: string } | null, enabled?: boolean }} options enabled 가 false 면 아무것도 부르지 않는다
 * @returns {{ messages: object[], readStates: { user_id: string, last_read_message_id: number }[] | null, status: "loading" | "ready" | "error", error: string, hasMore: boolean, loadingOlder: boolean, loadOlder: () => Promise<void>, send: (text: string) => Promise<void>, resend: (clientId: string) => Promise<void>, discard: (clientId: string) => void, retry: () => void }}
 */
export default function useChatMessages({ me, enabled = true }) {
  const [messages, setMessages] = useState([]);
  const [readStates, setReadStates] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);

  const ref = useRef([]); // 가장 최신 목록(비동기 콜백에서 읽는다)
  const alive = useRef(true);
  const inFlight = useRef(false);
  const again = useRef(false);
  const failures = useRef(0);
  const readFailures = useRef(0);
  const readTicks = useRef(0); // 마지막 읽음 조회 시도 뒤 지난 틱 수
  const readOff = useRef(false); // 404 를 받으면 이 세션 동안 조회를 끈다
  const older = useRef(false);
  const timer = useRef(null);
  const running = useRef(false);
  const generation = useRef(0);
  const counter = useRef(0);
  const cursor = useRef(0); // 새 메시지 확인 기준: 서버 조회로 실제 받은 가장 큰 id 만 반영한다(내가 보낸 메시지의 id 는 제외)
  const meRef = useRef(me);
  meRef.current = me;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, []);

  const update = useCallback((fn) => {
    ref.current = fn(ref.current);
    if (alive.current) setMessages(ref.current);
  }, []);

  /** 새 메시지 확인. 겹치면 건너뛰지 않고 끝난 뒤 한 번 더 한다. */
  const fetchNew = useCallback(
    async function run() {
      if (inFlight.current) {
        again.current = true;
        return;
      }
      inFlight.current = true;
      let more = false;
      try {
        const after = cursor.current;
        const first = after === 0;
        const rows = await listMessages(first ? { latest: true, limit: FIRST_PAGE } : { afterId: after, limit: POLL_PAGE });
        update((prev) => mergeMessages(prev, rows));
        cursor.current = Math.max(cursor.current, lastId(rows));
        if (first && alive.current) setHasMore(rows.length >= FIRST_PAGE);
        more = !first && rows.length >= POLL_PAGE; // 밀린 메시지가 더 있으면 바로 이어서
        failures.current = 0;
        if (alive.current) {
          setStatus("ready");
          setError("");
        }
      } catch (e) {
        failures.current += 1;
        if (alive.current) {
          setError(roomErrorMessage(e));
          setStatus((s) => (s === "loading" ? "error" : s));
        }
      } finally {
        inFlight.current = false;
        if (alive.current && (again.current || more)) {
          again.current = false;
          run();
        }
      }
    },
    [update],
  );

  /** 구성원별 읽음 위치 조회. 실패하면 숫자를 숨기고(null) 자체 실패 횟수만 올린다. 404 면 끈다. */
  const fetchReadStates = useCallback(async () => {
    if (readOff.current) return;
    readTicks.current = 0;
    try {
      const rows = await getReadStates();
      readFailures.current = 0;
      if (alive.current && Array.isArray(rows)) setReadStates(rows);
    } catch (e) {
      if (e?.status === 404) readOff.current = true;
      else readFailures.current += 1;
      if (alive.current) setReadStates(null);
    }
  }, []);

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
      await fetchNew();
      readTicks.current += 1;
      if (running.current && alive.current && generation.current === mine && readStatesDue(readTicks.current, readFailures.current)) await fetchReadStates();
      if (!running.current || !alive.current || generation.current !== mine) return;
      timer.current = setTimeout(tick, nextPollDelay(failures.current));
    };
    tick();
  }, [fetchNew, fetchReadStates]);

  // 화면이 보이고 앱이 앞에 있을 때만 확인한다
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

  const loadOlder = useCallback(async () => {
    if (older.current || !hasMore || ref.current.length === 0) return;
    const before = firstId(ref.current);
    if (!before) return;
    older.current = true;
    setLoadingOlder(true);
    try {
      const rows = await listMessages({ beforeId: before, limit: FIRST_PAGE });
      update((prev) => mergeMessages(prev, rows));
      if (alive.current && rows.length < FIRST_PAGE) setHasMore(false);
    } catch (e) {
      if (alive.current) setError(roomErrorMessage(e));
    } finally {
      older.current = false;
      if (alive.current) setLoadingOlder(false);
    }
  }, [hasMore, update]);

  const deliver = useCallback(
    async (clientId, text) => {
      try {
        const saved = await sendMessage(text);
        // 임시 메시지를 지우고 서버 메시지를 id 로 병합한다(폴링이 먼저 가져왔어도 중복되지 않는다)
        update((prev) => mergeMessages(prev.filter((m) => m.clientId !== clientId), [saved]));
      } catch {
        update((prev) => prev.map((m) => (m.clientId === clientId ? { ...m, status: "failed" } : m)));
      }
    },
    [update],
  );

  const send = useCallback(
    async (text) => {
      if (!canSend(text) || !meRef.current) return;
      const body = trimDraft(text);
      counter.current += 1;
      const clientId = `tmp-${Date.now()}-${counter.current}`;
      const temp = {
        id: clientId,
        clientId,
        user_id: meRef.current.id,
        user_name: meRef.current.name,
        text: body,
        created_at: new Date().toISOString(),
        status: "sending",
      };
      update((prev) => mergeMessages(prev, [temp]));
      await deliver(clientId, body);
    },
    [deliver, update],
  );

  const resend = useCallback(
    async (clientId) => {
      const target = ref.current.find((m) => m.clientId === clientId);
      if (!target) return;
      update((prev) => prev.map((m) => (m.clientId === clientId ? { ...m, status: "sending" } : m)));
      await deliver(clientId, target.text);
    },
    [deliver, update],
  );

  const discard = useCallback((clientId) => update((prev) => prev.filter((m) => m.clientId !== clientId)), [update]);

  const retry = useCallback(() => {
    failures.current = 0;
    readFailures.current = 0;
    readOff.current = false;
    if (ref.current.length === 0) setStatus("loading");
    fetchNew();
    fetchReadStates();
  }, [fetchNew, fetchReadStates]);

  return { messages, readStates, status, error, hasMore, loadingOlder, loadOlder, send, resend, discard, retry };
}
