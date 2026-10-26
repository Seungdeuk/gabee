import { useCallback, useEffect, useReducer, useRef } from "react";

import { listMedia } from "./api";
import { canLoadMore, initialMediaState, mediaReducer } from "./mediaState";

const PAGE = 40;

/**
 * 한 종류(kind)의 모음을 쪽(커서)으로 불러온다. kind·방이 바뀌면 처음부터 다시 받고 옛 응답은 버린다(전이 규칙은 mediaState.js).
 * counts 는 가장 최근 응답의 숫자라서 탭 글자에 쓴다.
 * @param {{ roomId?: string | null, kind: "image" | "file" | "video" }} args
 * @returns {{ items: object[], counts: { image: number, file: number, video: number }, status: "loading" | "ready" | "error", error: string, hasMore: boolean, loadingMore: boolean, loadMore: () => void, retry: () => void }}
 */
export default function useChatMedia({ roomId, kind }) {
  const [state, dispatch] = useReducer(mediaReducer, undefined, initialMediaState);
  const seq = useRef(0);
  const moreBusy = useRef(false); // 상태가 반영되기 전의 중복 호출 방지
  const latest = useRef(state);
  latest.current = state;

  const loadFirst = useCallback(() => {
    seq.current += 1;
    const mine = seq.current;
    moreBusy.current = false;
    dispatch({ type: "start", seq: mine });
    listMedia({ roomId, kind, limit: PAGE }).then(
      (page) => dispatch({ type: "firstOk", seq: mine, page }),
      (error) => dispatch({ type: "firstFail", seq: mine, error }),
    );
  }, [roomId, kind]);

  useEffect(() => {
    loadFirst();
    return () => {
      seq.current += 1; // 화면을 떠나거나 kind·방이 바뀌면 이전 응답은 번호가 달라 버려진다
    };
  }, [loadFirst]);

  const loadMore = useCallback(() => {
    const cur = latest.current;
    if (moreBusy.current || !canLoadMore(cur)) return;
    moreBusy.current = true;
    const mine = cur.seq;
    dispatch({ type: "moreStart", seq: mine });
    const done = () => {
      if (seq.current === mine) moreBusy.current = false;
    };
    listMedia({ roomId, kind, limit: PAGE, beforeId: cur.next }).then(
      (page) => {
        done();
        dispatch({ type: "moreOk", seq: mine, page });
      },
      (error) => {
        done();
        dispatch({ type: "moreFail", seq: mine, error });
      },
    );
  }, [roomId, kind]);

  return {
    items: state.items,
    counts: state.counts,
    status: state.status,
    error: state.error,
    hasMore: state.next != null,
    loadingMore: state.loadingMore,
    loadMore,
    retry: loadFirst,
  };
}
