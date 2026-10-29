import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

import { deleteMessage, getReadStates, getRoomInfo, listMessages, reactToMessage, removeReaction, sendMessage, sendPhoto } from "./api";
import { canSend, firstId, focusErrorMessage, isNoGroup, lastId, mergeMessages, nextPollDelay, photoSendErrorMessage, readStatesDue, roomErrorMessage, trimDraft } from "./chatUtils";
import { applySavedNow, beginTransition, canLoadNewer, canReuseLiveRun, canLoadOlder, canPoll, enterLiveEnd, finishTransition, initialModeState, needsLiveBeforeSend, retryTarget, tokenValid, windowToken } from "./focusMode";
import { FOCUS_PAGE, keepTemps, reachedLiveEnd, replaceWindow } from "./searchUtils";
import { markDeleted, markRepliesDeleted, refreshDue, refreshExisting, REFRESH_LIMIT, withMyReaction } from "./messageActions";

const FIRST_PAGE = 50;
const POLL_PAGE = 100;
const SEND_BLOCKED = "최신 대화로 돌아가지 못해 보내지 못했어요. 다시 시도해 주세요";

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
 *
 * 과거 보기(검색 결과로 이동): focusOn(id) 은 그 메시지 앞뒤 창(around_id)으로 목록을 통째로 바꾸고 새 메시지 확인(폴링)을 멈춘다 — 새 메시지 확인 기준(cursor)은 라이브 끝에 그대로 둔다.
 * 과거 보기 중에도 위(loadOlder)·아래(loadNewer)로 이어서 불러올 수 있고, 아래로 라이브 끝에 닿으면 자동으로 라이브로 돌아간다. returnToLive() 는 최근 50개를 다시 받아 라이브(폴링 재개)로 돌아간다.
 * 과거 보기에서 글·사진을 보내면 먼저 라이브로 돌아간 뒤 보낸다. initialFocus 가 있으면 처음부터 그 창으로 열고, 실패하면 최근 대화로 열고 안내 문구를 둔다.
 * @param {{ me: { id: string, name: string } | null, enabled?: boolean, roomId?: string | null, initialFocus?: number | null }} options enabled 가 false 면 아무것도 부르지 않는다, roomId 가 없으면 가족 전체방(방이 바뀌면 화면을 새로 연다)
 * @returns {{ recovered: number, focusing: boolean, focusTarget: { id: number, seq: number } | null, focusOn: (messageId: number) => Promise<boolean>, loadNewer: () => Promise<void>, loadingNewer: boolean, returnToLive: () => Promise<boolean>, messages: object[], readStates: { user_id: string, last_read_message_id: number }[] | null, status: "loading" | "ready" | "error", error: string, hasMore: boolean, loadingOlder: boolean, loadOlder: () => Promise<void>, send: (text: string, reply?: object | null) => Promise<boolean>, reactTo: (messageId: number|string, emoji: string | null) => Promise<{ ok: boolean, busy?: boolean, error?: object }>, deleteMine: (messageId: number|string) => Promise<{ ok: boolean, busy?: boolean, error?: object }>, sendImage: (asset: object) => Promise<boolean>, photoBusy: boolean, photoError: string, setPhotoError: (message: string) => void, resend: (clientId: string) => Promise<void>, discard: (clientId: string) => void, retry: () => void }}
 */
export default function useChatMessages({ me, enabled = true, roomId = null, initialFocus = null }) {
  const [messages, setMessages] = useState([]);
  const [readStates, setReadStates] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState("");
  const [focusing, setFocusing] = useState(initialFocus != null); // 과거 창을 보는 중(라이브 확인 멈춤)
  const [focusTarget, setFocusTarget] = useState(null); // 화면이 스크롤·강조할 메시지 { id, seq }
  const [loadingNewer, setLoadingNewer] = useState(false);
  const [recovered, setRecovered] = useState(0); // 포커스 실패로 최근 대화로 복구될 때마다 올라간다(화면이 맨 아래로 간다)

  const ms = useRef(initialModeState(initialFocus)); // 모드(live/past)·세대 번호·창 전환 중 여부(focusMode.js). 과거 모드이면 새 메시지 확인을 건너뛴다
  const liveRun = useRef(null); // 진행 중인 라이브 복귀 요청 { gen, promise }(세대가 같을 때만 겹쳐 부르면 같은 결과를 기다린다)
  const lastFail = useRef(null); // 과거 모드에서 마지막으로 실패한 동작(다시 시도용)
  const newer = useRef(false);
  const focusStarted = useRef(false);
  const photoLock = useRef(false); // 사진 보내기 중복 누름 방지(state 는 한 박자 늦다)
  const ref = useRef([]); // 가장 최신 목록(비동기 콜백에서 읽는다)
  const alive = useRef(true);
  const inFlight = useRef(false);
  const again = useRef(false);
  const failures = useRef(0);
  const readFailures = useRef(0);
  const refreshTicks = useRef(0); // 마지막 최근 메시지 다시 받기 뒤 지난 틱 수(반응·삭제를 따라가려고 가끔 다시 받는다)
  const mutating = useRef(0); // 내가 보낸 반응·삭제 요청 수(그동안은 다시 받은 응답을 반영하지 않는다)
  const busyMsg = useRef(new Set()); // 같은 메시지에 반응·삭제를 연타해도 한 번에 하나만 보낸다
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
  const roomRef = useRef(roomId); // 방은 화면이 열려 있는 동안 바뀌지 않는다
  roomRef.current = roomId;

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
      if (!canPoll(ms.current)) return; // 과거 창을 보는 동안(또는 창을 바꾸는 중)은 라이브 끝(cursor)을 건드리지 않는다
      if (inFlight.current) {
        again.current = true;
        return;
      }
      inFlight.current = true;
      let more = false;
      const token = windowToken(ms.current);
      try {
        const after = cursor.current;
        const first = after === 0;
        const rows = await listMessages(first ? { latest: true, limit: FIRST_PAGE, roomId: roomRef.current } : { afterId: after, limit: POLL_PAGE, roomId: roomRef.current });
        if (!tokenValid(ms.current, token) || !canPoll(ms.current)) return; // 요청 중에 과거 보기로 바뀌었으면 버린다
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
        if (tokenValid(ms.current, token) && canPoll(ms.current)) {
          failures.current += 1;
          if (alive.current) {
            setError(roomErrorMessage(e));
            setStatus((s) => (s === "loading" ? "error" : s));
          }
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

  /**
   * 열어 둔 화면이 다른 사람의 반응·삭제를 따라가도록 최근 메시지를 다시 받아, 이미 가진 메시지만 갱신한다(새 메시지는 새 메시지 확인 몫이라 넣지 않는다).
   * 내가 반응·삭제 요청 중이거나 과거 창을 보는 중이면 건너뛰고, 실패는 조용히 넘긴다.
   */
  const refreshVisible = useCallback(async () => {
    if (!canPoll(ms.current) || mutating.current > 0) return;
    const token = windowToken(ms.current);
    try {
      const rows = await listMessages({ latest: true, limit: REFRESH_LIMIT, roomId: roomRef.current });
      if (!alive.current || !tokenValid(ms.current, token) || !canPoll(ms.current) || mutating.current > 0) return; // 그 사이 창이 바뀌었거나 내가 바꾼 것이 있으면 오래된 응답이다
      update((prev) => refreshExisting(prev, rows));
    } catch {
      // 갱신이 안 돼도 다음 틱에 다시 한다
    }
  }, [update]);

  /** 구성원별 읽음 위치 조회. 실패하면 숫자를 숨기고(null) 자체 실패 횟수만 올린다. 404 면 끈다. */
  const fetchReadStates = useCallback(async () => {
    if (readOff.current) return;
    readTicks.current = 0;
    try {
      const rows = await getReadStates(roomRef.current);
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
      refreshTicks.current += 1;
      if (running.current && alive.current && generation.current === mine && refreshDue(refreshTicks.current)) {
        refreshTicks.current = 0;
        await refreshVisible();
      }
      readTicks.current += 1;
      if (running.current && alive.current && generation.current === mine && readStatesDue(readTicks.current, readFailures.current)) await fetchReadStates();
      if (!running.current || !alive.current || generation.current !== mine) return;
      timer.current = setTimeout(tick, nextPollDelay(failures.current));
    };
    tick();
  }, [fetchNew, fetchReadStates, refreshVisible]);

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
    if (older.current || !hasMore || ref.current.length === 0 || !canLoadOlder(ms.current)) return;
    const before = firstId(ref.current);
    if (!before) return;
    older.current = true;
    setLoadingOlder(true);
    const token = windowToken(ms.current);
    try {
      const rows = await listMessages({ beforeId: before, limit: FIRST_PAGE, roomId: roomRef.current });
      if (!alive.current || !tokenValid(ms.current, token)) return; // 요청 중에 창이 바뀌었으면 버린다
      update((prev) => mergeMessages(prev, rows));
      if (rows.length < FIRST_PAGE) setHasMore(false);
      if (ms.current.mode === "past") {
        lastFail.current = null;
        setError("");
      }
    } catch (e) {
      if (alive.current && tokenValid(ms.current, token)) {
        if (ms.current.mode === "past") lastFail.current = "older";
        setError(roomErrorMessage(e));
      }
    } finally {
      older.current = false;
      if (alive.current) setLoadingOlder(false);
    }
  }, [hasMore, update]);

  /**
   * 과거 창에서 라이브로 돌아간다: 최근 50개를 받아 서버 메시지를 통째로 바꾸고(임시 메시지는 유지) 새 메시지 확인 기준을 그 끝으로 맞춘 뒤 폴링을 이어 간다.
   * 이미 진행 중이면 그 결과를 같이 기다린다. 실패하면 과거 창에 머물고 오류를 둔다(아직 아무것도 못 받았으면 오류 상태).
   * @returns {Promise<boolean>} 라이브 상태가 됐으면 true(이미 라이브여도 true)
   */
  const returnToLive = useCallback(() => {
    if (ms.current.mode !== "past") return Promise.resolve(true);
    if (canReuseLiveRun(liveRun.current, ms.current)) return liveRun.current.promise; // 무효가 된(세대가 올라간) 요청은 기다리지 않고 새로 시작한다
    ms.current = beginTransition(ms.current, "live");
    const gen = ms.current.gen;
    const run = async () => {
      try {
        const rows = await listMessages({ latest: true, limit: FIRST_PAGE, roomId: roomRef.current });
        const fin = finishTransition(ms.current, gen, "live", true);
        if (!alive.current || !fin.applied) return false;
        ms.current = fin.state;
        ref.current = mergeMessages(keepTemps(ref.current), rows);
        setMessages(ref.current);
        cursor.current = lastId(rows);
        failures.current = 0;
        lastFail.current = null;
        setFocusing(false);
        setHasMore(rows.length >= FIRST_PAGE);
        setStatus("ready");
        setError("");
        setRecovered((n) => n + 1); // 화면이 위로 불러오기 잠금을 풀고 맨 아래로 간다
        return true;
      } catch (e) {
        const fin = finishTransition(ms.current, gen, "live", false);
        if (!alive.current || !fin.applied) return false;
        ms.current = fin.state;
        lastFail.current = "live";
        setError(roomErrorMessage(e));
        setStatus((s) => (s === "loading" ? "error" : s)); // 첫 화면이면 영구 스피너 대신 오류 화면
        return false;
      } finally {
        if (liveRun.current?.gen === gen) liveRun.current = null;
      }
    };
    const promise = run();
    liveRun.current = { gen, promise };
    return promise;
  }, []);

  /**
   * 그 메시지를 가운데로 한 창(around_id)을 불러와 목록을 바꾸고 과거 보기로 들어간다. 화면은 focusTarget 이 바뀌면 그 메시지로 스크롤·강조한다.
   * 실패하면 최근 대화(라이브)로 복구하고 안내 문구를 둔다. 복구도 실패하면 오류 상태다.
   * @param {number} messageId
   * @returns {Promise<boolean>} 창을 불러왔으면 true
   */
  const focusOn = useCallback(
    async (messageId) => {
      const id = Number(messageId);
      if (!Number.isInteger(id) || id < 1) return false;
      ms.current = beginTransition(ms.current, "focus");
      const gen = ms.current.gen;
      setFocusing(true);
      try {
        const rows = await listMessages({ aroundId: id, limit: FOCUS_PAGE, roomId: roomRef.current });
        const fin = finishTransition(ms.current, gen, "focus", true);
        if (!alive.current || !fin.applied) return false;
        ms.current = fin.state;
        ref.current = replaceWindow(ref.current, rows);
        setMessages(ref.current);
        lastFail.current = null;
        setHasMore(true); // 더 오래된 것이 있는지는 위로 불러 보면 안다
        setStatus("ready");
        setError("");
        setFocusTarget((prev) => ({ id, seq: (prev?.seq ?? 0) + 1 }));
        return true;
      } catch (e) {
        const fin = finishTransition(ms.current, gen, "focus", false);
        if (!alive.current || !fin.applied) return false;
        ms.current = fin.state;
        lastFail.current = "focus";
        const ok = await returnToLive(); // 아직 "past" 이므로 최근 50개로 목록을 새로 받는다
        if (ok && alive.current) setError(focusErrorMessage(e));
        return false;
      }
    },
    [returnToLive],
  );

  // 경로 인자로 처음부터 과거 창으로 여는 경우: 가족 정보가 준비되면 한 번만 불러온다
  useEffect(() => {
    if (!enabled || initialFocus == null || focusStarted.current) return;
    focusStarted.current = true;
    focusOn(initialFocus);
  }, [enabled, initialFocus, focusOn]);

  /** 과거 창의 아래쪽(이후 대화)을 이어서 불러온다. 기준은 창의 마지막 서버 id(임시 제외)다. 요청한 개수보다 적게 오면 라이브 끝에 닿은 것이라 자동으로 라이브로 돌아간다(다시 받지 않고 폴링 기준만 맞춘다). */
  const loadNewer = useCallback(async () => {
    if (newer.current || !canLoadNewer(ms.current)) return;
    const after = lastId(ref.current);
    if (!after) return;
    newer.current = true;
    setLoadingNewer(true);
    const token = windowToken(ms.current);
    try {
      const rows = await listMessages({ afterId: after, limit: FOCUS_PAGE, roomId: roomRef.current });
      if (!alive.current || !tokenValid(ms.current, token)) return;
      update((prev) => mergeMessages(prev, rows));
      lastFail.current = null;
      setError("");
      if (reachedLiveEnd(rows.length, FOCUS_PAGE)) {
        cursor.current = lastId(ref.current);
        ms.current = enterLiveEnd(ms.current);
        failures.current = 0;
        setFocusing(false);
      }
    } catch (e) {
      if (alive.current && tokenValid(ms.current, token)) {
        lastFail.current = "newer";
        setError(roomErrorMessage(e));
      }
    } finally {
      newer.current = false;
      if (alive.current) setLoadingNewer(false);
    }
  }, [update]);

  const deliver = useCallback(
    async (clientId, text, replyToId = null) => {
      try {
        const saved = await sendMessage(text, roomRef.current, replyToId);
        // 임시 메시지를 지우고 서버 메시지를 id 로 병합한다(폴링이 먼저 가져왔어도 중복되지 않는다). 그 사이 과거 창으로 옮겨 갔으면 병합하지 않는다.
        update((prev) => applySavedNow(prev, saved, ms.current, clientId));
      } catch {
        update((prev) => prev.map((m) => (m.clientId === clientId ? { ...m, status: "failed" } : m)));
      }
    },
    [update],
  );

  /** 과거 창이면 라이브로 돌아간 뒤에만 진행한다. 돌아가지 못하면 false 이고 안내 문구를 둔다(보내지 않는다). */
  const ensureLive = useCallback(async (report) => {
    if (!needsLiveBeforeSend(ms.current)) return true;
    if (await returnToLive()) return true;
    if (alive.current) (report ?? setError)(SEND_BLOCKED);
    return false;
  }, [returnToLive]);

  /**
   * 글을 보낸다. 과거 창에서는 먼저 라이브로 돌아가야 하고, 돌아가지 못하면 보내지 않는다(false).
   * @param {string} text
   * @param {{ id: number, user_name: string, text: string, deleted: boolean, has_attachment: boolean } | null} [reply] 답장이면 원본 미리보기(replyPreview)
   * @returns {Promise<boolean>} 보내기를 시작했으면 true(전송 실패는 목록의 "전송 실패" 로 보인다)
   */
  const send = useCallback(
    async (text, reply = null) => {
      if (!canSend(text) || !meRef.current) return false;
      if (!(await ensureLive())) return false;
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
        reply_to: reply,
      };
      update((prev) => mergeMessages(prev, [temp]));
      await deliver(clientId, body, reply?.id ?? null);
      return true;
    },
    [deliver, ensureLive, update],
  );

  /**
   * 사진 한 장을 보낸다. 과거 창에서는 먼저 라이브로 돌아가야 하고, 돌아가지 못하면 보내지 않는다. 성공하면 서버가 돌려준 메시지를 목록에 병합한다(임시 메시지 없음, 폴링이 먼저 가져와도 id 로 중복 제거).
   * 보내는 중에 다시 부르면 무시한다. 실패하면 photoError 에 사용자 문구를 둔다.
   * @param {{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string }} asset
   * @returns {Promise<boolean>} 보냈으면 true
   */
  const sendImage = useCallback(
    async (asset) => {
      if (photoLock.current || !meRef.current) return false;
      photoLock.current = true;
      setPhotoBusy(true);
      setPhotoError("");
      try {
        // 안내는 사진 오류 한 곳에만 둔다(상단 배너의 복귀 실패 문구는 지운다)
        if (!(await ensureLive((message) => { setError(""); setPhotoError(message); }))) return false;
        const saved = await sendPhoto(asset, roomRef.current);
        update((prev) => applySavedNow(prev, saved, ms.current, null));
        return true;
      } catch (e) {
        if (alive.current) setPhotoError(photoSendErrorMessage(e));
        return false;
      } finally {
        photoLock.current = false;
        if (alive.current) setPhotoBusy(false);
      }
    },
    [ensureLive, update],
  );

  const resend = useCallback(
    async (clientId) => {
      if (!(await ensureLive())) return;
      const target = ref.current.find((m) => m.clientId === clientId);
      if (!target) return;
      update((prev) => prev.map((m) => (m.clientId === clientId ? { ...m, status: "sending" } : m)));
      await deliver(clientId, target.text, target.reply_to?.id ?? null);
    },
    [deliver, ensureLive, update],
  );

  /** id 가 같은 서버 메시지만 바꾼다(임시 메시지는 건드리지 않는다). */
  const patchMessage = useCallback((id, patch) => update((prev) => prev.map((m) => (!m.clientId && Number(m.id) === id ? patch(m) : m))), [update]);

  /**
   * 내 반응을 정한다(emoji) 또는 지운다(emoji 가 null). 먼저 화면에 반영하고 실패하면 이전 반응으로 되돌린다.
   * 같은 메시지에 요청이 진행 중이거나 지운 메시지면 보내지 않는다.
   * @param {number|string} messageId
   * @param {string | null} emoji
   * @returns {Promise<{ ok: boolean, busy?: boolean, error?: object }>}
   */
  const reactTo = useCallback(
    async (messageId, emoji) => {
      const id = Number(messageId);
      const before = ref.current.find((m) => !m.clientId && Number(m.id) === id);
      if (!before || before.deleted) return { ok: false, error: { code: "message_deleted" } };
      if (busyMsg.current.has(id)) return { ok: false, busy: true };
      busyMsg.current.add(id);
      mutating.current += 1;
      patchMessage(id, (m) => withMyReaction(m, emoji));
      try {
        const saved = await (emoji ? reactToMessage({ roomId: roomRef.current, messageId: id, emoji }) : removeReaction({ roomId: roomRef.current, messageId: id }));
        patchMessage(id, (m) => ({ ...m, reactions: saved?.reactions ?? m.reactions })); // 서버가 센 값이 기준이다
        return { ok: true };
      } catch (error) {
        patchMessage(id, (m) => ({ ...m, reactions: before.reactions }));
        return { ok: false, error };
      } finally {
        busyMsg.current.delete(id);
        mutating.current -= 1;
      }
    },
    [patchMessage],
  );

  /**
   * 내가 보낸 메시지를 지운다. 먼저 "삭제된 메시지"로 바꿔 그리고(그 메시지를 인용한 답장도 삭제 표시) 실패하면 되돌린다.
   * @param {number|string} messageId
   * @returns {Promise<{ ok: boolean, busy?: boolean, error?: object }>}
   */
  const deleteMine = useCallback(
    async (messageId) => {
      const id = Number(messageId);
      const before = ref.current.find((m) => !m.clientId && Number(m.id) === id);
      if (!before) return { ok: false, error: { status: 404 } };
      if (before.deleted) return { ok: true };
      if (busyMsg.current.has(id)) return { ok: false, busy: true };
      busyMsg.current.add(id);
      mutating.current += 1;
      const quotedBefore = ref.current.filter((m) => m.reply_to?.id === id && !m.reply_to.deleted).map((m) => ({ id: m.id, reply_to: m.reply_to }));
      patchMessage(id, markDeleted);
      update((prev) => markRepliesDeleted(prev, id));
      try {
        await deleteMessage({ roomId: roomRef.current, messageId: id });
        return { ok: true };
      } catch (error) {
        patchMessage(id, () => before);
        update((prev) => prev.map((m) => (quotedBefore.some((q) => q.id === m.id) ? { ...m, reply_to: quotedBefore.find((q) => q.id === m.id).reply_to } : m)));
        return { ok: false, error };
      } finally {
        busyMsg.current.delete(id);
        mutating.current -= 1;
      }
    },
    [patchMessage, update],
  );

  const discard = useCallback((clientId) => update((prev) => prev.filter((m) => m.clientId !== clientId)), [update]);

  const retry = useCallback(() => {
    failures.current = 0;
    readFailures.current = 0;
    readOff.current = false;
    if (ref.current.length === 0) setStatus("loading");
    const action = retryTarget(lastFail.current, ms.current); // 과거 창에서는 마지막에 실패한 동작을 다시 한다
    if (action === "older") loadOlder();
    else if (action === "newer") loadNewer();
    else if (action === "live") returnToLive();
    else fetchNew();
    fetchReadStates();
  }, [fetchNew, fetchReadStates, loadNewer, loadOlder, returnToLive]);

  return { recovered, focusing, focusTarget, focusOn, loadNewer, loadingNewer, returnToLive, messages, readStates, status, error, hasMore, loadingOlder, loadOlder, send, sendImage, photoBusy, photoError, setPhotoError, resend, discard, retry, reactTo, deleteMine };
}
