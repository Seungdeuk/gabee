import { WEEKDAYS } from "../constants";

const pad = (n) => String(n).padStart(2, "0");

/**
 * @param {Date} date
 * @returns {string} "YYYY-MM-DD" (기기 현지 시간 기준)
 */
export function toDateKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * @param {string} key "YYYY-MM-DD"
 * @returns {Date} 현지 시간 자정
 */
export function fromDateKey(key) {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/**
 * @param {string} key "YYYY-MM-DD"
 * @param {number} days 더할 일수 (음수 가능)
 * @returns {string}
 */
export function addDays(key, days) {
  const d = fromDateKey(key);
  d.setDate(d.getDate() + days);
  return toDateKey(d);
}

/** @returns {string} 오늘의 "YYYY-MM-DD" */
export const todayKey = () => toDateKey(new Date());

/**
 * 선택한 날짜가 속한 주(일~토)의 날짜 키 7개.
 * @param {string} key
 * @returns {string[]}
 */
export function weekOf(key) {
  const start = addDays(key, -fromDateKey(key).getDay());
  return Array.from({ length: 7 }, (_, i) => addDays(start, i));
}

/**
 * 달력 한 달 칸. 앞쪽 빈 칸은 null.
 * @param {number} year
 * @param {number} month 1~12
 * @returns {(string | null)[]} 7의 배수 길이
 */
export function monthCells(year, month) {
  const lead = new Date(year, month - 1, 1).getDay();
  const days = new Date(year, month, 0).getDate();
  const cells = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= days; d += 1) cells.push(`${year}-${pad(month)}-${pad(d)}`);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

/**
 * @param {string} key
 * @returns {string} 예: "10월 21일 수요일"
 */
export function formatDateLong(key) {
  const d = fromDateKey(key);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${WEEKDAYS[d.getDay()]}요일`;
}

/**
 * @param {string} key
 * @returns {string} 예: "10.21 (수)"
 */
export function formatDateShort(key) {
  const d = fromDateKey(key);
  return `${d.getMonth() + 1}.${d.getDate()} (${WEEKDAYS[d.getDay()]})`;
}

/**
 * @param {string | null} time "HH:mm" 또는 null
 * @returns {string} 예: "오후 2:30". 시간이 없으면 빈 글자
 */
export function formatTime(time) {
  if (!time) return "";
  const [h, m] = time.split(":").map(Number);
  const period = h < 12 ? "오전" : "오후";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${period} ${hour}:${pad(m)}`;
}

/**
 * 카드에 쓰는 시간 범위. 종일이면 "종일", 시간이 없으면 빈 글자.
 * @param {{ allDay: boolean, startTime: string | null, endTime: string | null }} item
 * @returns {string}
 */
export function formatTimeRange({ allDay, startTime, endTime }) {
  if (allDay) return "종일";
  if (!startTime) return "";
  return endTime ? `${formatTime(startTime)} ~ ${formatTime(endTime)}` : formatTime(startTime);
}
