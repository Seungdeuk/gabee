import { shiftDay, todayKst } from "./timelineView";

/**
 * 여행 모드(일시정지) 날짜 계산의 순수 함수. 서버는 오늘(한국 시간)을 1일째로 세어 days 일째 날이 끝나는 자정에 다시 공유한다.
 * 예: 11/6 에 3일이면 11/8 까지 멈추고 11/9 0시에 재개한다.
 */
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const md = (date) => `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;

/**
 * 멈추는 마지막 날(그날까지 멈춘다).
 * @param {string} today 오늘 YYYY-MM-DD
 * @param {number} days 1~14
 * @returns {string} YYYY-MM-DD
 */
export function lastPauseDate(today, days) {
  return shiftDay(today, days - 1);
}

/**
 * 여행 모드를 걸기 전에 보여 줄 미리보기.
 * @param {string} today 오늘 YYYY-MM-DD
 * @param {number} days 1~14
 * @returns {{ lastDate: string, untilText: string, resumeText: string }}
 */
export function previewPause(today, days) {
  const lastDate = lastPauseDate(today, days);
  return { lastDate, untilText: `${md(lastDate)}까지`, resumeText: `${md(shiftDay(lastDate, 1))} 0시에 다시 공유해요` };
}

/**
 * 진행 중인 여행 모드의 D-day. 서버가 준 종료 시각(마지막 날의 다음 날 0시)에서 마지막 날을 구해 오늘과 비교한다.
 * @param {string} pausedUntilIso 서버의 paused_until
 * @param {number} [now] 현재 시각(ms), 시험용
 * @returns {{ lastDate: string, daysLeft: number, ddayText: string, untilText: string, resumeText: string }}
 */
export function describePause(pausedUntilIso, now = Date.now()) {
  const lastDate = new Date(new Date(pausedUntilIso).getTime() + KST_OFFSET_MS - 1).toISOString().slice(0, 10);
  const daysLeft = Math.max(0, Math.round((Date.parse(`${lastDate}T00:00:00Z`) - Date.parse(`${todayKst(now)}T00:00:00Z`)) / 86400000));
  return {
    lastDate,
    daysLeft,
    ddayText: daysLeft === 0 ? "D-day" : `D-${daysLeft}`,
    untilText: `${md(lastDate)}까지`,
    resumeText: `${md(shiftDay(lastDate, 1))} 0시에 자동으로 다시 공유해요`,
  };
}
