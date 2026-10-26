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
 * 오늘 이후(오늘 포함) 처음 오는 해당 요일. 이미 지났으면 다음 주.
 * @param {string} from "YYYY-MM-DD" 기준일
 * @param {number} weekday 0(일)~6(토)
 * @returns {string}
 */
export function nextWeekday(from, weekday) {
  return addDays(from, (weekday - fromDateKey(from).getDay() + 7) % 7);
}

/**
 * 선택한 날짜가 속한 주의 날짜 키 7개.
 * @param {string} key
 * @param {boolean} [mondayStart] true 면 월~일(메인), false 면 일~토(달력)
 * @returns {string[]}
 */
export function weekOf(key, mondayStart = true) {
  const day = fromDateKey(key).getDay();
  const start = addDays(key, -(mondayStart ? (day + 6) % 7 : day));
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
 * @returns {string} 예: "2026년 10월 24일 토요일"
 */
export function formatDateWithYear(key) {
  return `${fromDateKey(key).getFullYear()}년 ${formatDateLong(key)}`;
}

/**
 * @param {string} key
 * @returns {string} 예: "10월 22일"
 */
export function formatMonthDay(key) {
  const d = fromDateKey(key);
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/**
 * 채팅 기록에 쓰는 시각 글자. 오늘은 시각만, 어제는 "어제 + 시각", 그보다 앞은 날짜만 보여 준다.
 * @param {number} timestamp 밀리초
 * @param {number} [now] 기준 시각(밀리초)
 * @returns {string} 예: "오전 10:12", "어제 오후 6:40", "10월 18일"
 */
export function formatChatTime(timestamp, now = Date.now()) {
  const d = new Date(timestamp);
  const key = toDateKey(d);
  const today = toDateKey(new Date(now));
  const hour = d.getHours();
  const clock = `${hour < 12 ? "오전" : "오후"} ${hour % 12 === 0 ? 12 : hour % 12}:${pad(d.getMinutes())}`;
  if (key === today) return clock;
  if (key === addDays(today, -1)) return `어제 ${clock}`;
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/**
 * 카드 문장에 쓰는 줄인 날짜.
 * @param {string} key "YYYY-MM-DD"
 * @returns {string} 예: "1/2"
 */
export function formatSlashDate(key) {
  const d = fromDateKey(key);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/**
 * 카드 오른쪽에 쓰는 24시간 표기. 종일이거나 시간이 없으면 빈 글자.
 * @param {{ allDay: boolean, startTime: string | null, endTime: string | null }} item
 * @param {string} [separator] 시작과 끝 사이 글자
 * @returns {string} 예: "09:00–10:00"
 */
export function formatClockRange({ allDay, startTime, endTime }, separator = "–") {
  if (allDay || !startTime) return "";
  return endTime ? `${startTime}${separator}${endTime}` : startTime;
}

/**
 * @param {string} key
 * @returns {string} 예: "2026년 10월"
 */
export function formatYearMonth(key) {
  const d = fromDateKey(key);
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
}

/**
 * 다른 달로 옮길 때 고를 날짜. 오늘이 그 달이면 오늘, 아니면 1일.
 * @param {string} key 지금 선택한 날짜
 * @param {number} delta 옮길 달 수 (음수 가능)
 * @returns {string}
 */
export function shiftMonthKey(key, delta) {
  const d = fromDateKey(key);
  const target = toDateKey(new Date(d.getFullYear(), d.getMonth() + delta, 1));
  const today = todayKey();
  return today.slice(0, 7) === target.slice(0, 7) ? today : target;
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
 * 시간 범위를 오전·오후로 풀어 쓴 글자. 종일이면 "종일", 시간이 없으면 빈 글자.
 * @param {{ allDay: boolean, startTime: string | null, endTime: string | null }} item
 * @param {string} [separator] 시작과 끝 사이 글자
 * @returns {string} 예: "오전 8:00 – 오후 4:00"
 */
export function formatTimeRange({ allDay, startTime, endTime }, separator = " ~ ") {
  if (allDay) return "종일";
  if (!startTime) return "";
  return endTime ? `${formatTime(startTime)}${separator}${formatTime(endTime)}` : formatTime(startTime);
}

/**
 * 등록 화면에서 확정된 시간을 보여 주는 글자. 24시간 표기 옆에 오전·오후로 풀어 쓴 글자를 괄호로 덧붙여 어르신도 알아보기 쉽게 한다.
 * @param {{ allDay: boolean, startTime: string | null, endTime: string | null }} item
 * @returns {string} 예: "14:00 – 16:00 (오후 2:00 – 오후 4:00)". 종일이면 "종일", 시간이 없으면 빈 글자
 */
export function formatTimeConfirmed(item) {
  if (item.allDay) return "종일";
  if (!item.startTime) return "";
  return `${formatClockRange(item, " – ")} (${formatTimeRange(item, " – ")})`;
}
