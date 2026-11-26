import { useCallback, useEffect, useReducer, useRef } from "react";

import { listTimelinePhotos } from "./api";
import {
  ANALYSIS_POLL_MS,
  canLoadMoreTimeline,
  initialTimelineState,
  shouldPollAnalysis,
  timelineReducer,
} from "./timeline";

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
  const polls = useRef(0); // 정리 중이라 자동으로 다시 받은 횟수
  const pagedMore = useRef(false); // 다음 쪽을 이미 불렀으면 자동 갱신이 목록을 덮어쓰지 않는다

  const loadFirst = useCallback(() => {
    seq.current += 1;
    const mine = seq.current;
    moreBusy.current = false;
    polls.current = 0;
    pagedMore.current = false;
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

  useEffect(() => {
    // 서버가 사진을 정리하는 동안(분석 중) 조용히 다시 받는다: 새로고침을 여러 번 누르지 않아도 되게. 횟수 상한이 있다.
    if (pagedMore.current || !shouldPollAnalysis(state, polls.current)) return undefined;
    const mine = state.seq;
    const timer = setTimeout(() => {
      polls.current += 1;
      listTimelinePhotos({ limit: PAGE }).then(
        (page) => {
          if (!pagedMore.current) dispatch({ type: "refreshOk", seq: mine, page });
        },
        () => {}, // 조용한 갱신의 실패는 화면을 바꾸지 않는다(새로고침 버튼은 그대로 있다)
      );
    }, ANALYSIS_POLL_MS);
    return () => clearTimeout(timer);
  }, [state]);

  const loadMore = useCallback(() => {
    const cur = latest.current;
    if (moreBusy.current || !canLoadMoreTimeline(cur)) return;
    moreBusy.current = true;
    pagedMore.current = true;
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
    analyzing: state.analyzing,
    analysisFailed: state.analysisFailed,
    loadMore,
    retry: loadFirst,
    remove,
  };
}
