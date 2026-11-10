import { useEffect, useState } from "react";

import { usageGauges, usedRatio } from "@/shared/aiUsage";

import { getAiUsage } from "./api";

/**
 * 구독 관리 화면의 사용량 게이지. 화면이 열릴 때 한 번 읽는다.
 * status: "loading" | "ready"(gauges 있음) | "unavailable"(가족이 없거나 서버가 값을 주지 않음/불러오기 실패)
 * @returns {{ status: "loading" | "ready" | "unavailable", gauges: { key: string, label: string, ratio: number, percent: number, high: boolean }[] }}
 */
export function useAiUsage() {
  const [state, setState] = useState({ status: "loading", gauges: [] });
  useEffect(() => {
    let alive = true;
    getAiUsage()
      .then((raw) => {
        if (!alive) return;
        const gauges = usageGauges({
          userUsed: usedRatio(raw?.limits?.user_per_day, raw?.usage?.user_today),
          groupUsed: usedRatio(raw?.limits?.group_per_day, raw?.usage?.group_today),
        });
        setState(gauges.length > 0 ? { status: "ready", gauges } : { status: "unavailable", gauges: [] });
      })
      .catch(() => {
        if (alive) setState({ status: "unavailable", gauges: [] });
      });
    return () => {
      alive = false;
    };
  }, []);
  return state;
}
