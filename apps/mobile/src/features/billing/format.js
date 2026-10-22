/** @param {number} n 정수 원 @returns {string} 예: 12,300원 */
export const won = (n) => `${Number(n).toLocaleString("ko-KR")}원`;

/** @returns {string} 이번 달 YYYY-MM (기기 시간 기준) */
export function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** @param {string} month YYYY-MM @param {number} delta 더할 달 수(음수 가능) @returns {string} */
export function shiftMonth(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** @param {string} text 사용자가 입력한 금액 @returns {number} 정수 원, 숫자가 아니면 NaN */
export const parseWon = (text) => (/^\d+$/.test(text.trim()) ? parseInt(text.trim(), 10) : NaN);
