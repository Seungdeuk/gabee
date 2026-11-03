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
 * 마이 > AI 리포트 데이터. 일정·문서를 병렬로 한 번만 받아 두고, 주 이동은 서버 호출 없이 다시 계산한다.
 * @returns {{
 *   status: "loading" | "ready" | "error" | "nofamily",
 *   errorMessage: string,
 *   range: ReturnType<typeof weekRange>,
 *   report: ReturnType<typeof buildReport> | null,
 *   docsStatus: "ok" | "loading" | "failed",
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
  const [docs, setDocs] = useState(null);
  const [docsStatus, setDocsStatus] = useState("loading");
  const alive = useRef(true);
  const loadId = useRef(0); // 오래된 응답이 새 응답을 덮어쓰지 않게 한다

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    const id = (loadId.current += 1);
    setNow(currentTime());
    setStatus("loading");
    setDocsStatus("loading");
    const [ev, dc] = await Promise.allSettled([listSharedEvents(), listSharedDocuments()]);
    if (!alive.current || id !== loadId.current) return;
    if (ev.status === "rejected") {
      const e = describeError(ev.reason);
      const noGroup = e.noGroup || (dc.status === "rejected" && describeError(dc.reason).noGroup);
      setErrorMessage(e.message);
      setStatus(noGroup ? "nofamily" : "error");
      return;
    }
    setEvents(Array.isArray(ev.value) ? ev.value : []);
    if (dc.status === "fulfilled") {
      setDocs(Array.isArray(dc.value) ? dc.value : []);
      setDocsStatus("ok");
    } else {
      setDocs(null);
      setDocsStatus("failed");
    }
    setStatus("ready");
  }, []);

  const retryDocs = useCallback(async () => {
    const id = loadId.current;
    setDocsStatus("loading");
    try {
      const items = await listSharedDocuments();
      if (!alive.current || id !== loadId.current) return;
      setDocs(Array.isArray(items) ? items : []);
      setDocsStatus("ok");
    } catch {
      if (!alive.current || id !== loadId.current) return;
      setDocs(null);
      setDocsStatus("failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const range = useMemo(() => weekRange(now, offset), [now, offset]);
  const report = useMemo(
    () => (status === "ready" && events ? buildReport({ events, docs, range, today: todayKst(now) }) : null),
    [status, events, docs, range, now],
  );

  const goPrev = useCallback(() => setOffset((o) => (canGoBack(o) ? o - 1 : o)), []);
  const goNext = useCallback(() => setOffset((o) => (canGoForward(o) ? o + 1 : o)), []);
  const goCurrent = useCallback(() => setOffset(0), []);

  return {
    status,
    errorMessage,
    range,
    report,
    docsStatus,
    canPrev: canGoBack(offset),
    canNext: canGoForward(offset),
    goPrev,
    goNext,
    goCurrent,
    retry: load,
    retryDocs,
  };
}
