import { useCallback, useEffect, useRef, useState } from "react";

import { listRooms, searchMessages } from "./api";
import { searchErrorMessage } from "./chatUtils";
import { familyRoomId, isLatestRequest, mergeSearchResults, normalizeQuery, SEARCH_DEBOUNCE_MS, SEARCH_PAGE, searchTerms, shouldRunSearch, stepSearchIndex } from "./searchUtils";

const IDLE = { status: "idle", items: [], next: null, q: "", error: "", loadingMore: false, moreError: "", index: 0 };

/**
 * 대화 글자 검색(키워드 일치만, AI 없음). 입력을 300ms 쉬었다가 한 번 부르고, 같은 검색어는 다시 부르지 않으며, 더 새 요청이 시작되면 이전 응답은 버린다.
 * 결과는 최신순이고 index 0 이 가장 최근 일치다. 새 검색이 끝나면 index 0 에서 시작하고, step 으로 더 오래된/더 최근 일치로 옮기며(끝에서 서버에 더 있으면 다음 쪽을 받아 이어 간다) current 가 지금 가리키는 일치다.
 * 검색어·결과 글자는 화면 상태에만 두고 로그·저장소에 남기지 않는다.
 * @param {{ roomId?: string | null, scoped?: boolean, debounceMs?: number }} [options] roomId 가 없으면 내가 접근할 수 있는 모든 방. scoped 이면 한 방 안 검색이라 roomId 를 알기 전(null)에는 검색하지 않는다(blocked) — 모든 방 검색으로 떨어지지 않게
 * @returns {{ blocked: boolean, query: string, setQuery: (text: string) => void, reset: () => void, terms: string[], status: "idle" | "loading" | "ready" | "error", items: object[], index: number, current: object | null, step: (dir: "older" | "newer") => Promise<void>, error: string, hasMore: boolean, loadingMore: boolean, moreError: string, loadMore: () => Promise<void>, retry: () => void }}
 */
export default function useChatSearch({ roomId = null, scoped = false, debounceMs = SEARCH_DEBOUNCE_MS } = {}) {
  const blocked = scoped && !roomId;
  const [query, setQuery] = useState("");
  const [state, setState] = useState(IDLE);
  const stateRef = useRef(state);
  stateRef.current = state;
  const seq = useRef(0); // 가장 최근 요청 번호
  const lastQ = useRef(""); // 직전에 요청한 검색어
  const moreBusy = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const run = useCallback(
    async (q) => {
      seq.current += 1;
      const mine = seq.current;
      lastQ.current = q;
      moreBusy.current = false;
      setState({ ...IDLE, status: "loading", q });
      try {
        const page = await searchMessages({ q, roomId, limit: SEARCH_PAGE });
        if (!alive.current || !isLatestRequest(mine, seq.current)) return;
        setState({ ...IDLE, status: "ready", q, items: mergeSearchResults([], page.items), next: page.next_before_id ?? null });
      } catch (e) {
        if (!alive.current || !isLatestRequest(mine, seq.current)) return;
        lastQ.current = ""; // 실패한 검색어는 다시 시도할 수 있게 한다
        setState({ ...IDLE, status: "error", q, error: searchErrorMessage(e) });
      }
    },
    [roomId],
  );

  useEffect(() => {
    const q = normalizeQuery(query);
    if (!q || blocked) {
      seq.current += 1; // 진행 중이던 응답을 버린다
      lastQ.current = "";
      setState(IDLE);
      return undefined;
    }
    if (!shouldRunSearch(q, lastQ.current)) return undefined;
    const timer = setTimeout(() => run(q), debounceMs);
    return () => clearTimeout(timer);
  }, [query, run, debounceMs, blocked]);

  const loadMore = useCallback(async () => {
    const cur = stateRef.current;
    if (cur.status !== "ready" || cur.next == null || moreBusy.current) return false;
    moreBusy.current = true;
    const mine = seq.current;
    setState((s) => ({ ...s, loadingMore: true, moreError: "" }));
    try {
      const page = await searchMessages({ q: cur.q, roomId, limit: SEARCH_PAGE, beforeId: cur.next });
      if (!alive.current || !isLatestRequest(mine, seq.current)) return;
      setState((s) => ({ ...s, items: mergeSearchResults(s.items, page.items), next: page.next_before_id ?? null, loadingMore: false }));
      return true;
    } catch (e) {
      if (alive.current && isLatestRequest(mine, seq.current)) setState((s) => ({ ...s, loadingMore: false, moreError: searchErrorMessage(e) }));
      return false;
    } finally {
      if (isLatestRequest(mine, seq.current)) moreBusy.current = false;
    }
  }, [roomId]);

  const step = useCallback(
    async (dir) => {
      const cur = stateRef.current;
      if (cur.status !== "ready") return;
      const next = stepSearchIndex({ index: cur.index, count: cur.items.length, hasMore: cur.next != null, dir });
      if (!next.more) {
        if (next.index !== cur.index) setState((s) => ({ ...s, index: next.index }));
        return;
      }
      const before = cur.items.length;
      if (!(await loadMore())) return;
      setState((s) => (s.q === cur.q && s.items.length > before ? { ...s, index: before } : s)); // 다시 그리기 전의 ref 가 아니라 최신 상태로 판단한다
    },
    [loadMore],
  );

  const retry = useCallback(() => {
    const q = normalizeQuery(query);
    if (q) run(q);
  }, [query, run]);

  const reset = useCallback(() => setQuery(""), []);

  return {
    blocked,
    query,
    setQuery,
    reset,
    terms: searchTerms(state.q),
    status: state.status,
    items: state.items,
    index: state.index,
    current: state.status === "ready" ? (state.items[state.index] ?? null) : null,
    step,
    error: state.error,
    hasMore: state.next != null,
    loadingMore: state.loadingMore,
    moreError: state.moreError,
    loadMore,
    retry,
  };
}

/**
 * 가족 전체방의 실제 방 id(방 목록의 kind "family" 행). 가족방 안 검색의 범위로 쓴다. enabled 가 false 면(1:1 방) 부르지 않는다.
 * @param {boolean} enabled
 * @returns {{ status: "loading" | "ready" | "error", id: string | null, retry: () => void }}
 */
export function useFamilyRoomId(enabled) {
  const [state, setState] = useState({ status: "loading", id: null });
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(async () => {
    setState({ status: "loading", id: null });
    try {
      const id = familyRoomId(await listRooms());
      if (alive.current) setState(id ? { status: "ready", id } : { status: "error", id: null });
    } catch {
      if (alive.current) setState({ status: "error", id: null });
    }
  }, []);
  useEffect(() => {
    if (enabled) load();
  }, [enabled, load]);
  return { ...state, retry: load };
}
