import { toDateKey } from "./date";

const pad = (n) => String(n).padStart(2, "0");

/** 하루의 마지막 시각(분 단위). 끝 시간을 자동으로 채울 때 이보다 넘기지 않는다. */
const LAST_MINUTE = 23 * 60 + 55;

/**
 * @param {string} time "HH:mm"
 * @returns {{ period: "오전" | "오후", hour: number, minute: number }} hour 는 1~12
 */
export function to12h(time) {
  const [h, m] = time.split(":").map(Number);
  return { period: h < 12 ? "오전" : "오후", hour: h % 12 === 0 ? 12 : h % 12, minute: m };
}

/**
 * @param {{ period: "오전" | "오후", hour: number, minute: number }} t hour 는 1~12
 * @returns {string} "HH:mm"
 */
export function from12h({ period, hour, minute }) {
  const h = (hour % 12) + (period === "오후" ? 12 : 0);
  return `${pad(h)}:${pad(minute)}`;
}

/**
 * 입력 칸(시·분 영역)에 보여 줄 값. 24시간 표기다. 예: 14:30 → ["14", "30"]
 * @param {string} time "HH:mm"
 * @returns {string[]}
 */
export function time24Blocks(time) {
  return time.split(":");
}

/**
 * 입력 칸에 친 시·분을 시각으로 바꾼다. 화면은 모두 24시간 표기이고, 오전·오후는 입력할 때의 변환 보조다.
 * 1~12시로 치면 골라 둔 오전·오후(period)에 맞춘다(오후에서 "11" → 23:00, 오전에서 "11" → 11:00).
 * 0시와 13~23시는 쓴 그대로이고, 13~23시는 오후로 본다.
 * @param {string} hour 두 자리 "00"~"23"
 * @param {string} minute 두 자리 "00"~"59"
 * @param {"오전" | "오후"} period
 * @returns {string | null} "HH:mm". 올바른 시각이 아니면 null
 */
export function timeFromBlocks(hour, minute, period) {
  if (!/^\d{2}$/.test(hour) || !/^\d{2}$/.test(minute)) return null;
  const h = Number(hour);
  const m = Number(minute);
  if (h > 23 || m > 59) return null;
  return h === 0 || h >= 13 ? `${pad(h)}:${pad(m)}` : from12h({ period, hour: h, minute: m });
}

/**
 * 오전·오후 버튼을 눌렀을 때의 시각. 오전은 12시 이후면 12시간을 빼고, 오후는 12시 전이면 12시간을 더한다.
 * @param {string} time "HH:mm"
 * @param {"오전" | "오후"} period
 * @returns {string} "HH:mm"
 */
export function withPeriod(time, period) {
  const [h, m] = time.split(":").map(Number);
  const next = period === "오전" ? (h >= 12 ? h - 12 : h) : h < 12 ? h + 12 : h;
  return `${pad(next)}:${pad(m)}`;
}

/**
 * 끝 시간 자동 채움용. 자정을 넘기지 않게 23:55 에서 멈춘다.
 * @param {string} time "HH:mm"
 * @param {number} minutes 더할 분
 * @returns {string} "HH:mm"
 */
export function addMinutes(time, minutes) {
  const [h, m] = time.split(":").map(Number);
  const total = Math.min(h * 60 + m + minutes, LAST_MINUTE);
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

/**
 * 날짜 입력 칸의 연·월·일을 날짜로 바꾼다. 작년·내년도 그대로 받는다.
 * @param {string} year 네 자리
 * @param {string} month 두 자리
 * @param {string} day 두 자리
 * @returns {string | null} "YYYY-MM-DD". 비어 있거나 없는 날짜(2026-02-30)이면 null
 */
export function dateFromBlocks(year, month, day) {
  if (!/^\d{4}$/.test(year) || !/^\d{2}$/.test(month) || !/^\d{2}$/.test(day)) return null;
  const y = Number(year);
  const m = Number(month);
  const d = Number(day);
  const date = new Date(y, m - 1, d);
  if (date.getFullYear() !== y || date.getMonth() !== m - 1 || date.getDate() !== d) return null;
  return toDateKey(date);
}
