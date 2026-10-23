import { useCallback, useEffect, useState } from "react";

/**
 * 1초마다 줄어드는 남은 시간(초). restart(초) 로 다시 시작하고, 0 이 되면 멈춘다.
 * @param {number} initial 처음 남은 시간(초). 0 이면 멈춘 상태로 시작한다
 * @returns {{ remaining: number, restart: (seconds: number) => void }}
 */
export default function useCountdown(initial = 0) {
  const [remaining, setRemaining] = useState(initial);

  useEffect(() => {
    if (remaining <= 0) return undefined;
    const timer = setTimeout(() => setRemaining((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [remaining]);

  const restart = useCallback((seconds) => setRemaining(seconds), []);
  return { remaining, restart };
}
