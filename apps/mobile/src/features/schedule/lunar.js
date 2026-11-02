import KoreanLunarCalendar from "korean-lunar-calendar";

import { fromDateKey, toDateKey } from "./utils/date";

// 양력 <-> 음력 변환(한국천문연구원 기준, 오프라인). 라이브러리가 지원하는 범위(양력 1000-02-13 ~ 2050-12-31)를
// 벗어나거나 없는 날짜면 null 이다. 일정은 항상 양력("YYYY-MM-DD")으로 저장하고, 음력은 보여 주거나 입력받을 때만 쓴다.

const calendar = new KoreanLunarCalendar();
const cache = new Map();

/**
 * 양력 날짜의 음력.
 * @param {string} dateKey "YYYY-MM-DD"
 * @returns {{ year: number, month: number, day: number, leap: boolean } | null}
 */
export function solarToLunar(dateKey) {
  if (cache.has(dateKey)) return cache.get(dateKey);
  const d = fromDateKey(dateKey);
  let result = null;
  if (calendar.setSolarDate(d.getFullYear(), d.getMonth() + 1, d.getDate())) {
    const l = calendar.getLunarCalendar();
    result = { year: l.year, month: l.month, day: l.day, leap: Boolean(l.intercalation) };
  }
  cache.set(dateKey, result);
  return result;
}

/**
 * 음력 날짜의 양력.
 * @param {number} year 음력 연도
 * @param {number} month 1~12
 * @param {number} day 1~30
 * @param {boolean} [leap] 윤달이면 true
 * @returns {string | null} "YYYY-MM-DD", 없는 날짜(그 달에 30일이 없음, 윤달이 없음, 지원 범위 밖)면 null
 */
export function lunarToSolar(year, month, day, leap = false) {
  if (!calendar.setLunarDate(year, month, day, leap)) return null;
  const s = calendar.getSolarCalendar();
  return toDateKey(new Date(s.year, s.month - 1, s.day));
}

/**
 * 달력 칸에 쓰는 짧은 글: 음력 1일(초하루)만 "10.1", 윤달이면 "윤 10.1". 다른 날은 null.
 * @param {string} dateKey
 * @returns {string | null}
 */
export function firstDayLabel(dateKey) {
  const l = solarToLunar(dateKey);
  if (!l || l.day !== 1) return null;
  return `${l.leap ? "윤 " : ""}${l.month}.1`;
}
