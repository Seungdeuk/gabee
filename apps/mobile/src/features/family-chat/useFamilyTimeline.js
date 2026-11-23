import { useCallback, useEffect, useReducer, useRef } from "react";

import { listTimelinePhotos } from "./api";
import { canLoadMoreTimeline, initialTimelineState, timelineReducer } from "./timeline";

const PAGE = 30;

/**
 * 가족 타임라인을 쪽(커서)으로 불러온다. 다시 시도하거나 화면을 떠나면 옛 응답은 번호(seq)가 달라 버려진다(전이 규칙은 timeline.js).
 * @returns {{ items: object[], status: "loading" | "ready" | "error", error: string, next: string | null, hasMore: boolean, loadingMore: boolean, loadMore: () => void, retry: () => void, remove: (id: string) => void }}
 */
export default function useFamilyTimeline() {
  const [state, dispatch] = useReducer(timelineReducer, undefined, initialTimelineState);
  const seq = useRef(0);
  const moreBusy = useRef(false); // 상태가 반영되기 전의 중복 호출 방지
  const latest = useRef(state);
  latest.current = state;

  const loadFirst = useCallback(() => {
    seq.current += 1;
    const mine = seq.current;
    moreBusy.current = false;
    dispatch({ type: "start", seq: mine });
    listTimelinePhotos({ limit: PAGE }).then(
      (page) => dispatch({ type: "firstOk", seq: mine, page }),
      (error) => dispatch({ type: "firstFail", seq: mine, error }),
    );
  }, []);

  useEffect(() => {
    loadFirst();
    return () => {
      seq.current += 1; // 화면을 떠나면 이전 응답은 번호가 달라 버려진다
    };
  }, [loadFirst]);

  const loadMore = useCallback(() => {
    const cur = latest.current;
    if (moreBusy.current || !canLoadMoreTimeline(cur)) return;
    moreBusy.current = true;
    const mine = cur.seq;
    dispatch({ type: "moreStart", seq: mine });
    const done = () => {
      if (seq.current === mine) moreBusy.current = false;
    };
    listTimelinePhotos({ limit: PAGE, before: cur.next }).then(
      (page) => {
        done();
        dispatch({ type: "moreOk", seq: mine, page });
      },
      (error) => {
        done();
        dispatch({ type: "moreFail", seq: mine, error });
      },
    );
  }, []);

  const remove = useCallback((id) => dispatch({ type: "removed", id }), []);

  return {
    items: state.items,
    status: state.status,
    error: state.error,
    next: state.next,
    hasMore: state.next != null,
    loadingMore: state.loadingMore,
    loadMore,
    retry: loadFirst,
    remove,
  };
}
