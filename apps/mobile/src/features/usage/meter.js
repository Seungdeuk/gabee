// 체류시간 측정기 — 화면·타이머 없이 "앞에 온 시각"과 "뒤로 간 시각·탭을 옮긴 시각"의 차이로만 탭별 시간을 모은다.

import { localDay } from "./tabs";

// 백그라운드에 이보다 짧게 있다가 돌아오면 같은 사용으로 보고 실행 횟수를 세지 않는다
const SAME_VISIT_MS = 30 * 60 * 1000;

/**
 * 체류시간 측정기. 화면과 상관없는 보통 객체라 값이 바뀌어도 화면을 다시 그리지 않는다.
 * @param {string} firstTab 처음 보고 있는 탭
 * @param {(report: {day: string, opens: number, tabs: Record<string, number>}) => Promise<void>} send 서버로 보내는 함수
 * @returns {{setAuthed: (on: boolean, now: number, active: boolean) => void, moveTo: (tab: string, now: number) => void, begin: (now: number) => void, finish: (now: number) => void}}
 */
export function createMeter(firstTab, send) {
  let authed = false;
  let tab = firstTab; // 지금 보고 있는 탭
  let since = null; // 지금 탭을 보기 시작한 시각(ms). 백그라운드면 null
  let spent = {}; // 탭 → 이번 사용에서 머문 ms
  let opens = 0; // 이번에 보낼 실행 횟수
  let lastBackground = null; // 마지막으로 뒤로 간 시각(ms)

  /** 지금 탭에 머문 시간을 더하고 재기 시작점을 now 로 옮긴다. */
  const settle = (now) => {
    if (since === null) return;
    if (now > since) spent[tab] = (spent[tab] || 0) + (now - since);
    since = now;
  };

  /** 앱이 앞으로 왔다(또는 로그인했다): 재기 시작. 오래 쉬었다 왔으면 실행 1번. */
  const begin = (now) => {
    if (!authed || since !== null) return;
    if (lastBackground === null || now - lastBackground >= SAME_VISIT_MS) opens += 1;
    since = now;
  };

  /** 앱이 뒤로 갔다: 재기를 멈추고 모은 값을 한 번 보낸 뒤 비운다. 실패하면 버린다. */
  const finish = (now) => {
    settle(now);
    since = null;
    lastBackground = now;
    const tabs = {};
    for (const [name, ms] of Object.entries(spent)) {
      const sec = Math.round(ms / 1000);
      if (sec > 0) tabs[name] = sec;
    }
    const report = { day: localDay(new Date(now)), opens, tabs };
    spent = {};
    opens = 0;
    if (!authed || (report.opens === 0 && Object.keys(tabs).length === 0)) return;
    send(report).catch(() => {
      // 서버 준비 전(404·503)이나 네트워크 실패: 버린다
    });
  };

  return {
    setAuthed(on, now, active) {
      authed = on;
      if (!on) {
        since = null;
        spent = {};
        opens = 0;
        return;
      }
      if (active) begin(now);
    },
    moveTo(next, now) {
      if (next === tab) return;
      settle(now);
      tab = next;
    },
    begin,
    finish,
  };
}
