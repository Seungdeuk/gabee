import { describePause } from "./travel";

/**
 * 위치 탭 맨 위 상태 줄. 어느 탭에서든 지금 공유 상태를 한눈에 보인다.
 * @param {{ enabled: boolean, consent: boolean, paused: boolean, paused_until: string | null, background: boolean } | null | undefined} me
 * @param {number} [now] 현재 시각(ms), 시험용
 * @returns {{ tone: "ok" | "pause" | "off", text: string }}
 */
export function statusLine(me, now = Date.now()) {
  if (!me) return { tone: "off", text: "상태를 불러오는 중이에요" };
  if (!me.enabled) return { tone: "off", text: "이 서버에서는 위치 공유가 꺼져 있어요" };
  if (!me.consent) return { tone: "off", text: "공유 꺼짐" };
  if (me.paused && me.paused_until) {
    const p = describePause(me.paused_until, now);
    return { tone: "pause", text: `여행 모드 · ${p.ddayText} · ${p.untilText}` };
  }
  return { tone: "ok", text: me.background ? "공유 중 · 앱을 꺼도 켜져 있어요" : "공유 중 · 앱이 켜져 있을 때만" };
}
