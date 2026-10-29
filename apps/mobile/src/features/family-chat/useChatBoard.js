import { useCallback, useEffect, useReducer, useRef } from "react";

import { deleteBoardPost, listBoard } from "./api";
import { boardDeleteOutcome, boardReducer, canLoadMoreBoard, initialBoardState } from "./boardUtils";

const PAGE = 20;

/**
 * 게시판 목록(지난 공지 포함)을 쪽(커서)으로 불러온다. 방이 바뀌면 처음부터 다시 받고 옛 응답은 버린다(전이 규칙은 boardUtils.js).
 * @param {{ roomId?: string | null }} args roomId 가 없으면 가족 전체방
 * @returns {{ items: object[], status: "loading" | "ready" | "error", error: string, hasMore: boolean, loadingMore: boolean, loadMore: () => void, retry: () => void, remove: (id: string) => Promise<{ effect: "remove" | "keep", notice: string } | null> }}
 */
export default function useChatBoard({ roomId }) {
  const [state, dispatch] = useReducer(boardReducer, undefined, initialBoardState);
  const seq = useRef(0);
  const moreBusy = useRef(false); // 상태가 반영되기 전의 중복 호출 방지
  const deleting = useRef(new Set()); // 삭제 중인 글 id: 같은 글을 두 번 지우지 않는다
  const latest = useRef(state);
  latest.current = state;

  const loadFirst = useCallback(() => {
    seq.current += 1;
    const mine = seq.current;
    moreBusy.current = false;
    dispatch({ type: "start", seq: mine });
    listBoard({ roomId, limit: PAGE }).then(
      (page) => dispatch({ type: "firstOk", seq: mine, page }),
      (error) => dispatch({ type: "firstFail", seq: mine, error }),
    );
  }, [roomId]);

  useEffect(() => {
    loadFirst();
    return () => {
      seq.current += 1; // 화면을 떠나거나 방이 바뀌면 이전 응답은 번호가 달라 버려진다
    };
  }, [loadFirst]);

  const loadMore = useCallback(() => {
    const cur = latest.current;
    if (moreBusy.current || !canLoadMoreBoard(cur)) return;
    moreBusy.current = true;
    const mine = cur.seq;
    dispatch({ type: "moreStart", seq: mine });
    const done = () => {
      if (seq.current === mine) moreBusy.current = false;
    };
    listBoard({ roomId, limit: PAGE, before: cur.next }).then(
      (page) => {
        done();
        dispatch({ type: "moreOk", seq: mine, page });
      },
      (error) => {
        done();
        dispatch({ type: "moreFail", seq: mine, error });
      },
    );
  }, [roomId]);

  /**
   * 글을 삭제한다(구성원 누구나). 성공하거나 이미 없는 글이면 목록에서 뺀다. 같은 글을 이미 지우는 중이면 null.
   * @param {string} id 게시판 글 id
   * @returns {Promise<{ effect: "remove" | "keep", notice: string } | null>}
   */
  const remove = useCallback(
    async (id) => {
      if (deleting.current.has(id)) return null;
      deleting.current.add(id);
      let error = null;
      try {
        await deleteBoardPost({ roomId, postId: id });
      } catch (e) {
        error = e ?? { status: -1 };
      } finally {
        deleting.current.delete(id);
      }
      const outcome = boardDeleteOutcome(error);
      if (outcome.effect === "remove") dispatch({ type: "removed", id });
      return outcome;
    },
    [roomId],
  );

  return { items: state.items, status: state.status, error: state.error, hasMore: state.next != null, loadingMore: state.loadingMore, loadMore, retry: loadFirst, remove };
}
