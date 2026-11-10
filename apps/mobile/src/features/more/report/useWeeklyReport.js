import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "@/shared/api/client";

import { listSharedDocuments, listSharedEvents } from "../api";
import { buildReport, canGoBack, canGoForward, todayKst, weekRange } from "./weekReport";

// 개발용: 오늘 날짜를 바꾼다(EXPO_PUBLIC_DEV_TODAY=YYYY-MM-DD, billing 과 같은 방식). 비우면 실제 오늘.
const DEV_TODAY = process.env.EXPO_PUBLIC_DEV_TODAY ?? "";

/**
 * 지금 시각(밀리초). 개발용 날짜가 올바르면 그 날짜 KST 정오로 바꾼다.
 * @returns {number}
 */
function currentTime() {
  if (/^\d{4}-\d{2}-\d{2}$/.test(DEV_TODAY)) {
    const t = Date.parse(`${DEV_TODAY}T12:00:00+09:00`);
    if (!Number.isNaN(t)) return t;
  }
  return Date.now();
}

/**
 * 호출 실패를 사람이 읽을 문구와 가족 없음 여부로 바꾼다.
 * @param {unknown} error
 * @returns {{ noGroup: boolean, message: string }}
 */
function describeError(error) {
  const isApi = error instanceof ApiError;
  return {
    noGroup: isApi && error.code === "no_group",
    message: (isApi && error.message) || "불러오지 못했어요",
  };
}

/**
 * 마이 > AI 리포트 데이터. 일정은 첫 진입에 한 번만 받고, 문서는 주(offset)마다 그 주 범위로 조회해
 * docsByOffset 캐시에 둔다(한 번 본 주는 다시 부르지 않는다). 주 이동 때 캐시에 없으면 그 주 문서만 받는다.
 * 캐시 값: { status: "ok", items } | { status: "failed" }. 값이 없으면 받는 중.
 * @returns {{
 *   status: "loading" | "ready" | "error" | "nofamily",
 *   errorMessage: string,
 *   range: ReturnType<typeof weekRange>,
 *   report: ReturnType<typeof buildReport> | null,
 *   docsStatus: "ok" | "loading" | "failed",
 *   docsRetrying: boolean,
 *   canPrev: boolean, canNext: boolean,
 *   goPrev: () => void, goNext: () => void, goCurrent: () => void,
 *   retry: () => void, retryDocs: () => void,
 * }}
 */
export function useWeeklyReport() {
  const [offset, setOffset] = useState(0);
  const [now, setNow] = useState(currentTime);
  const [status, setStatus] = useState("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [events, setEvents] = useState(null);
  const [docsByOffset, setDocsByOffset] = useState({});
  const [retryingOffset, setRetryingOffset] = useState(null);
  const alive = useRef(true);
  const loadId = useRef(0); // 첫 진입·retry 마다 올린다. 오래된 응답이 새 응답을 덮어쓰지 않게 한다
  const offsetRef = useRef(0);
  const inFlight = useRef(new Set()); // 지금 받는 중인 offset(같은 주를 두 번 부르지 않는다)

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    offsetRef.current = offset;
  }, [offset]);

  /**
   * 한 주의 문서를 받아 캐시에 넣는다(실패해도 던지지 않는다).
   * @param {number} off 주 offset
   * @param {number} nowMs 기준 시각
   * @param {number} id 요청한 시점의 loadId
   * @param {boolean} [force] true 면 받는 중이어도 다시 받는다(문서 다시 불러오기)
   * @returns {Promise<{ noGroup: boolean }>}
   */
  const fetchDocs = useCallback(async (off, nowMs, id, force = false) => {
    if (!force && inFlight.current.has(off)) return { noGroup: false };
    inFlight.current.add(off);
    const { start, end } = weekRange(nowMs, off);
    let entry;
    let noGroup = false;
    try {
      const items = await listSharedDocuments({ from: start, to: end });
      entry = { status: "ok", items: Array.isArray(items) ? items : [] };
    } catch (error) {
      noGroup = describeError(error).noGroup;
      entry = { status: "failed" };
    }
    if (id !== loadId.current) return { noGroup };
    inFlight.current.delete(off);
    if (!alive.current) return { noGroup };
    setDocsByOffset((prev) => ({ ...prev, [off]: entry }));
    return { noGroup };
  }, []);

  const load = useCallback(async () => {
    const id = (loadId.current += 1);
    const nowMs = currentTime();
    inFlight.current.clear();
    setNow(nowMs);
    setStatus("loading");
    setDocsByOffset({});
    setRetryingOffset(null);
    const [ev, dc] = await Promise.allSettled([listSharedEvents(), fetchDocs(offsetRef.current, nowMs, id)]);
    if (!alive.current || id !== loadId.current) return;
    const docsNoGroup = dc.status === "fulfilled" && dc.value.noGroup;
    if (ev.status === "rejected") {
      const e = describeError(ev.reason);
      setErrorMessage(e.message);
      setStatus(e.noGroup || docsNoGroup ? "nofamily" : "error");
      return;
    }
    setEvents(Array.isArray(ev.value) ? ev.value : []);
    setStatus("ready"); // 일정은 성공하고 문서만 실패한 경우(no_group 포함)는 문서만 실패로 보여 준다
  }, [fetchDocs]);

  useEffect(() => {
    load();
  }, [load]);

  // 주를 옮겼는데 그 주 문서가 아직 없으면 그 주만 받는다(status 는 ready 그대로).
  const currentEntry = docsByOffset[offset];
  useEffect(() => {
    if (status === "ready" && !currentEntry) fetchDocs(offset, now, loadId.current);
  }, [status, offset, now, currentEntry, fetchDocs]);

  const retryDocs = useCallback(async () => {
    const off = offsetRef.current;
    const id = loadId.current;
    setRetryingOffset(off);
    await fetchDocs(off, now, id, true);
    if (alive.current && id === loadId.current) setRetryingOffset((cur) => (cur === off ? null : cur)); // 다른 주의 재시도 표시를 지우지 않는다
  }, [fetchDocs, now]);

  const range = useMemo(() => weekRange(now, offset), [now, offset]);
  const docsRetrying = retryingOffset === offset;
  let docsStatus = "loading";
  if (currentEntry) docsStatus = currentEntry.status === "ok" ? "ok" : "failed";

  const report = useMemo(() => {
    if (status !== "ready" || !events) return null;
    const today = todayKst(now);
    if (docsRetrying || docsStatus === "failed") return buildReport({ events, docs: null, range, today });
    if (docsStatus === "loading") return buildReport({ events, docs: null, range, today, docsPending: true });
    return buildReport({ events, docs: currentEntry.items, range, today });
  }, [status, events, docsStatus, docsRetrying, currentEntry, range, now]);

  const goPrev = useCallback(() => setOffset((o) => (canGoBack(o) ? o - 1 : o)), []);
  const goNext = useCallback(() => setOffset((o) => (canGoForward(o) ? o + 1 : o)), []);
  const goCurrent = useCallback(() => setOffset(0), []);

  return {
    status,
    errorMessage,
    range,
    report,
    docsStatus,
    docsRetrying,
    canPrev: canGoBack(offset),
    canNext: canGoForward(offset),
    goPrev,
    goNext,
    goCurrent,
    retry: load,
    retryDocs,
  };
}
