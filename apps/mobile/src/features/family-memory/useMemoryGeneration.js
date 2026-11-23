import { useCallback, useEffect, useReducer, useRef } from "react";

import { useAuth } from "@/shared/auth/AuthProvider";
import { memoryUiMode } from "@/shared/memoryFlag";

import { getMemoryGeneration, requestMemoryGeneration } from "./api";
import { GENERATION_POLL_MS, createSingleFlight, generationReducer, initialGenerationState, shouldKeepPolling, shouldReloadCandidates } from "./generation";
import { scopeKey } from "./memories";

/**
 * 사용자 요청형 추억 생성(PR10)의 상태와 "추억 만들기" 동작. 서버 입구가 꺼져 있으면(404) hidden=true 로 패널을 숨긴다. 개발용 mock 모드·로그아웃에서는 부르지 않는다.
 * 요청은 멱등이라 처리 중에는 같은 요청을 일정 간격으로 다시 보내 진행을 확인하고, 후보가 달라지면 onChanged 로 후보 목록을 다시 불러오게 한다.
 * 사용자·가족이 바뀌면 이전 상태·예약된 확인·늦은 응답을 모두 버린다.
 * @param {() => void} onChanged 후보 목록을 다시 불러오는 함수
 * @returns {{ state: ReturnType<typeof initialGenerationState>, polling: boolean, start: () => void }}
 */
export default function useMemoryGeneration(onChanged) {
  const { user } = useAuth();
  const scope = scopeKey(user);
  const enabled = memoryUiMode() === "on";
  const [state, dispatch] = useReducer(generationReducer, undefined, initialGenerationState);
  const seq = useRef(0);
  const prev = useRef(null);
  const polls = useRef(0);
  const timer = useRef(null);
  const polling = useRef(false);
  const flight = useRef(createSingleFlight());
  const changed = useRef(onChanged);
  changed.current = onChanged;

  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    polling.current = false;
  }, []);

  const apply = useCallback(
    (mine, gen, step, explicit) => {
      dispatch({ type: "ok", seq: mine, gen });
      if (shouldReloadCandidates(prev.current, gen, explicit)) changed.current?.();
      prev.current = gen;
      if (shouldKeepPolling(gen, polls.current)) {
        polling.current = true;
        timer.current = setTimeout(step, GENERATION_POLL_MS);
      } else {
        polling.current = false;
      }
    },
    [],
  );

  const run = useCallback(
    (call, fresh, explicit = false, onSettled = null) => {
      if (!scope || !enabled) {
        onSettled?.();
        return;
      }
      const mine = seq.current;
      if (fresh) polls.current = 0;
      else polls.current += 1;
      clear();
      dispatch({ type: "start", seq: mine });
      call().then(
        (gen) => {
          onSettled?.();
          if (mine !== seq.current) return; // 가족·사용자가 바뀌었다
          apply(mine, gen, () => run(requestMemoryGeneration, false), explicit);
        },
        (error) => {
          onSettled?.();
          if (mine !== seq.current) return;
          dispatch({ type: "fail", seq: mine, error });
        },
      );
    },
    [scope, enabled, apply, clear],
  );

  useEffect(() => {
    seq.current += 1;
    prev.current = null;
    flight.current.reset(); // 가족·사용자가 바뀌면 이전 범위의 요청 중 표시를 푼다
    clear();
    dispatch({ type: "scope", scope, seq: seq.current });
    if (scope && enabled) run(getMemoryGeneration, true);
    return () => {
      seq.current += 1; // 화면이 사라지면 예약된 확인과 늦은 응답을 버린다
      clear();
    };
  }, [scope, enabled, run, clear]);

  const start = useCallback(() => {
    if (!flight.current.tryStart()) return; // 이미 요청 중이면 연타를 무시한다
    run(requestMemoryGeneration, true, true, () => flight.current.done());
  }, [run]);
  return { state, polling: polling.current, start };
}