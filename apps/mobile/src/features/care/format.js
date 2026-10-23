const pad = (n) => String(n).padStart(2, "0");

/** @param {string} hhmm "HH:MM" @returns {number} 자정부터의 분 */
export const toMinutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));

/** @param {number} m 분(0 이상) @returns {string} 예: 45분, 1시간 20분 */
export const hm = (m) => (m >= 60 ? `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""}` : `${m}분`);

/** 예정 시각까지 남은 분을 말로 바꾼다. @param {number} minutes 지났으면 음수 @returns {string} 예: 40분 후, 지금, 20분 지났어요 */
export const untilText = (minutes) => (minutes > 0 ? `${hm(minutes)} 후` : minutes === 0 ? "지금" : `${hm(-minutes)} 지났어요`);

/** @param {number} minutes 예정 시각이 지난 분 @returns {string} 예: 3시간 전 */
export const agoText = (minutes) => `${hm(Math.max(0, minutes))} 전`;

export { pad };
