import { useCallback, useEffect, useRef } from "react";
import { AppState } from "react-native";

import { fetchNudges } from "../api";

const MIN_GAP_MS = 5 * 60 * 1000; // 앱을 오가며 열 때마다 서버를 부르지 않게 최소 간격을 둔다
const TIMER_SLACK_MS = 2000; // 타이머가 조금 일찍 울려도 건너뛰지 않게 하는 여유

/**
 * 앱을 열 때(그리고 다른 앱에서 돌아올 때) 가비가 먼저 챙겨 줄 말을 받아 채팅에 넣는다.
 * 앱이 앞에 떠 있는 동안에도 같은 간격(5분)으로 다시 확인하고, 백그라운드로 가면 멈춘다.
 * 서버가 한 번 준 말은 다시 주지 않으므로 같은 말이 반복되지 않는다. 먼저 말하기가 꺼져 있으면 서버가 빈 목록을 준다.
 *
 * @param {{ enabled: boolean, busy?: boolean, onNudges: (texts: string[]) => void }} options enabled 는 로그인이 끝났는지, busy 는 가비가 답하는 중이라 끼어들면 안 되는지, onNudges 는 말 목록을 채팅에 넣는 함수
 */
export default function useNudges({ enabled, busy = false, onNudges }) {
  const lastRun = useRef(0);
  const running = useRef(false);
  const busyRef = useRef(busy);
  busyRef.current = busy;

  const run = useCallback(async () => {
    if (!enabled || busyRef.current || running.current || Date.now() - lastRun.current < MIN_GAP_MS - TIMER_SLACK_MS) return;
    running.current = true;
    lastRun.current = Date.now();
    try {
      const list = await fetchNudges();
      if (list.length > 0) onNudges(list);
    } finally {
      running.current = false;
    }
  }, [enabled, onNudges]);

  useEffect(() => {
    let timer = null;
    const start = () => {
      if (timer === null) timer = setInterval(run, MIN_GAP_MS);
    };
    const stop = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };
    run();
    if (AppState.currentState === "active") start();
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        run();
        start();
      } else {
        stop();
      }
    });
    return () => {
      stop();
      sub.remove();
    };
  }, [run]);
}
