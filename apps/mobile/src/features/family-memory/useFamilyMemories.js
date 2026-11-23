import { useCallback, useEffect, useReducer, useRef } from "react";

import { useAuth } from "@/shared/auth/AuthProvider";
import { evictPhotoCache } from "@/shared/imageCache";

import { listMemoryCandidates } from "./api";
import { loadMockCandidates } from "./fixtures";
import { initialMemoriesState, memoriesReducer, normalizeCandidates, photoGoneAction, removedPhotoPaths, scopeKey } from "./memories";
import { memoryUiMode } from "@/shared/memoryFlag";

/**
 * 현재 가족의 추억 후보를 불러온다(읽기 전용). 사용자·가족(활성 가족 id)이 바뀌거나 로그아웃하면 후보를 즉시 비우고 새로 불러온다 —
 * 다른 가족의 후보가 화면에 남지 않는다. 늦게 온 응답은 번호(seq)가 달라 버려진다. mock 모드(개발)는 API 를 부르지 않고 합성 데이터를 쓴다.
 * @returns {{ state: object, refresh: () => void, photoGone: (candidateId: string, attachmentId: string) => void }}
 */
export default function useFamilyMemories() {
  const { user } = useAuth();
  const scope = scopeKey(user);
  const mode = memoryUiMode();
  const [state, dispatch] = useReducer(memoriesReducer, undefined, initialMemoriesState);
  const seq = useRef(0);

  // 범위가 바뀌면(다른 가족·다른 사용자·로그아웃) 이전 목록과 진행 중이던 응답을 버린다
  useEffect(() => {
    seq.current += 1;
    dispatch({ type: "scope", scope, seq: seq.current });
  }, [scope]);

  const load = useCallback(() => {
    if (!scope) return; // 로그인하지 않았으면 부르지 않는다
    seq.current += 1;
    const mine = seq.current;
    dispatch({ type: "start", seq: mine });
    const call = mode === "mock" ? loadMockCandidates : listMemoryCandidates;
    call().then(
      (data) => dispatch({ type: "ok", seq: mine, items: normalizeCandidates(data) }),
      (error) => dispatch({ type: "fail", seq: mine, error }),
    );
  }, [scope, mode]);

  useEffect(() => {
    load();
    return () => {
      seq.current += 1; // 화면이 사라지면 이전 응답은 버려진다
    };
  }, [load]);

  // 목록에서 사라진 사진(서버가 뺐거나 가족·로그인이 바뀜)의 기기 캐시 사본을 지운다. 채팅에서 볼 수 있는 사진은 다시 받으면 되고, 원본 사진 자체는 건드리지 않는다
  const shown = useRef([]);
  useEffect(() => {
    const gone = removedPhotoPaths(shown.current, state.items);
    shown.current = state.items;
    if (gone.length > 0) evictPhotoCache(gone);
  }, [state.items]);

  const photoGone = useCallback(
    (candidateId, attachmentId) => {
      const action = photoGoneAction(mode, candidateId, attachmentId);
      if (action) dispatch(action);
    },
    [mode],
  );
  return { state, refresh: load, photoGone };
}