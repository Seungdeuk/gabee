import { useCallback, useEffect, useRef, useState } from "react";

import { createWeeklyNews, getWeeklyNews } from "../api";

const POLL_MS = 5000; // 만드는 중(pending)이면 이 간격으로 다시 읽는다
const POLL_MAX = 12;

/**
 * 한 주의 가족 뉴스를 읽고, 사용자가 누르면 만든다. 주(weekStart)가 바뀌면 새로 읽는다.
 * 만드는 중(pending)이면 잠시 간격을 두고 다시 읽는다(최대 1분).
 * @param {{ weekStart: string, enabled: boolean }} args enabled=false 면 아무것도 부르지 않는다(가족 없음 등)
 * @returns {{
 *   phase: "loading" | "loaded" | "error",
 *   news: object | null,
 *   error: unknown,
 *   creating: boolean,
 *   createError: unknown,
 *   reload: () => void,
 *   create: () => Promise<void>,
 * }}
 */
export function useWeeklyNews({ weekStart, enabled }) {
  const [phase, setPhase] = useState("loading");
  const [news, setNews] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  const loadId = useRef(0); // 주를 옮기거나 다시 읽을 때 올려, 오래된 응답이 새 화면을 덮지 않게 한다
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(
    async (silent = false) => {
      const id = (loadId.current += 1);
      if (!silent) {
        setPhase("loading");
        setCreateError(null);
        setCreating(false);
      }
      try {
        const next = await getWeeklyNews(weekStart);
        if (!alive.current || id !== loadId.current) return;
        setNews(next);
        setError(null);
        setPhase("loaded");
      } catch (e) {
        if (!alive.current || id !== loadId.current) return;
        if (silent) return; // 다시 읽기 실패는 이미 보이는 화면을 그대로 둔다
        setError(e);
        setPhase("error");
      }
    },
    [weekStart],
  );

  useEffect(() => {
    if (enabled) load();
  }, [enabled, load]);

  const pending = phase === "loaded" && news?.status === "pending";
  useEffect(() => {
    if (!pending) return undefined;
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      if (n > POLL_MAX) clearInterval(timer);
      else load(true);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [pending, load]);

  const create = useCallback(async () => {
    const id = (loadId.current += 1);
    setCreating(true);
    setCreateError(null);
    try {
      const next = await createWeeklyNews(weekStart);
      if (!alive.current || id !== loadId.current) return;
      setNews(next);
      setPhase("loaded");
    } catch (e) {
      if (!alive.current || id !== loadId.current) return;
      setCreateError(e);
    } finally {
      if (alive.current && id === loadId.current) setCreating(false);
    }
  }, [weekStart]);

  return { phase, news, error, creating, createError, reload: () => load(), create };
}
