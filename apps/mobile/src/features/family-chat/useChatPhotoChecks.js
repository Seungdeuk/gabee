import { useCallback, useEffect, useReducer, useRef } from "react";

import { listMyPhotoChecks } from "./api";
import { canLoadMoreReview, initialReviewState, reviewReducer } from "./photoChecks";

const PAGE = 20;

/**
 * "확인이 필요한 사진" 목록을 쪽(커서)으로 불러온다. 다시 시도하거나 화면을 떠나면 옛 응답은 번호(seq)가 달라 버려진다(전이 규칙은 photoChecks.js).
 * @returns {{ items: object[], total: number, status: "loading" | "ready" | "error", error: string, hasMore: boolean, loadingMore: boolean, loadMore: () => void, retry: () => void, remove: (id: string) => void }}
 */
export default function useChatPhotoChecks(kind = "review") {
  const [state, dispatch] = useReducer(reviewReducer, undefined, initialReviewState);
  const seq = useRef(0);
  const moreBusy = useRef(false); // 상태가 반영되기 전의 중복 호출 방지
  const latest = useRef(state);
  latest.current = state;

  const loadFirst = useCallback(() => {
    seq.current += 1;
    const mine = seq.current;
    moreBusy.current = false;
    dispatch({ type: "start", seq: mine });
    listMyPhotoChecks({ limit: PAGE, kind }).then(
      (page) => dispatch({ type: "firstOk", seq: mine, page }),
      (error) => dispatch({ type: "firstFail", seq: mine, error }),
    );
  }, [kind]);

  useEffect(() => {
    loadFirst();
    return () => {
      seq.current += 1; // 화면을 떠나면 이전 응답은 번호가 달라 버려진다
    };
  }, [loadFirst]);

  const loadMore = useCallback(() => {
    const cur = latest.current;
    if (moreBusy.current || !canLoadMoreReview(cur)) return;
    moreBusy.current = true;
    const mine = cur.seq;
    dispatch({ type: "moreStart", seq: mine });
    const done = () => {
      if (seq.current === mine) moreBusy.current = false;
    };
    listMyPhotoChecks({ limit: PAGE, before: cur.next, kind }).then(
      (page) => {
        done();
        dispatch({ type: "moreOk", seq: mine, page });
      },
      (error) => {
        done();
        dispatch({ type: "moreFail", seq: mine, error });
      },
    );
  }, [kind]);

  const remove = useCallback((id) => dispatch({ type: "removed", id }), []);

  return {
    items: state.items,
    total: state.total,
    status: state.status,
    error: state.error,
    hasMore: state.next != null,
    loadingMore: state.loadingMore,
    loadMore,
    retry: loadFirst,
    remove,
  };
}
