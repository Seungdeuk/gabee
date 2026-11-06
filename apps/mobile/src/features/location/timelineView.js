/**
 * 이동 기록 타임라인 화면의 순수 계산(앱 모듈 없이 시험할 수 있게 따로 둔다). 날짜는 한국 시간(KST) 기준 YYYY-MM-DD 다.
 */
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/**
 * 한국 시간 기준 오늘 날짜.
 * @param {number} [now] 현재 시각(ms), 시험용
 * @returns {string} YYYY-MM-DD
 */
export function todayKst(now = Date.now()) {
  return new Date(now + KST_OFFSET_MS).toISOString().slice(0, 10);
}

/**
 * 날짜를 하루 단위로 옮긴다.
 * @param {string} date YYYY-MM-DD
 * @param {number} delta 옮길 날 수(음수면 이전)
 * @returns {string}
 */
export function shiftDay(date, delta) {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

/**
 * "11월 9일 (월)" 모양의 날짜 이름.
 * @param {string} date YYYY-MM-DD
 * @returns {string}
 */
export function dayLabel(date) {
  const d = new Date(`${date}T00:00:00Z`);
  return `${d.getUTCMonth() + 1}월 ${d.getUTCDate()}일 (${"일월화수목금토"[d.getUTCDay()]})`;
}

/**
 * 서버가 준 시각(ISO, 시간대 포함)을 한국 시간 "HH:MM" 으로.
 * @param {string} iso
 * @returns {string}
 */
export function hhmm(iso) {
  return new Date(new Date(iso).getTime() + KST_OFFSET_MS).toISOString().slice(11, 16);
}

/**
 * 머문·이동한 시간을 "1시간 20분" 처럼 짧게.
 * @param {string} startIso
 * @param {string} endIso
 * @returns {string}
 */
export function durationText(startIso, endIso) {
  const minutes = Math.max(0, Math.round((new Date(endIso) - new Date(startIso)) / 60000));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h && m) return `${h}시간 ${m}분`;
  if (h) return `${h}시간`;
  return `${m}분`;
}

/**
 * 구간 하나를 화면에 보일 한 줄 글과 모양으로 바꾼다. 이름이 없는 곳은 "이름 없는 곳", 기록 없음은 원인을 단정하지 않는다.
 * @param {{ kind: "stay" | "move" | "no_record" | "anomaly", start: string, end: string, place?: string | null, origin?: string | null }} seg
 * @returns {{ time: string, title: string, sub: string, tone: "normal" | "muted" | "warn" }}
 */
export function describeSegment(seg) {
  const time = `${hhmm(seg.start)} ~ ${hhmm(seg.end)}`;
  const span = durationText(seg.start, seg.end);
  if (seg.kind === "no_record") {
    return { time, title: "기록 없음", sub: `${span} · 앱이 꺼져 있었거나 신호가 없었거나 위치 공유를 멈춘 시간이에요`, tone: "muted" };
  }
  if (seg.kind === "move") {
    const from = seg.origin ?? "이름 없는 곳";
    const to = seg.place ?? "이름 없는 곳";
    const route = seg.origin || seg.place ? `${from} → ${to}` : "이동 중";
    return { time, title: route, sub: `이동 · ${span}`, tone: "normal" };
  }
  const name = seg.place ?? "이름 없는 곳";
  if (seg.kind === "anomaly") {
    return { time, title: `${name}에서 머묾`, sub: `평소 활동 구역 밖 · ${span}`, tone: "warn" };
  }
  return { time, title: `${name}에서 머묾`, sub: span, tone: "normal" };
}

/** 위치 기록을 보관하는 날 수(오늘 포함). 서버 LOCATION_RETENTION_DAYS 기본값과 같다. */
export const KEEP_DAYS = 14;
const WEEKDAYS = "일월화수목금토";

/**
 * date 가 속한 주(일요일 시작)의 7일을 날짜순으로.
 * @param {string} date YYYY-MM-DD
 * @param {number} [weekOffset] 몇 주 전인지(0=이번 주, 1=지난 주)
 * @returns {string[]}
 */
export function weekDates(date, weekOffset = 0) {
  const base = shiftDay(date, -weekOffset * 7);
  const start = shiftDay(base, -new Date(`${base}T00:00:00Z`).getUTCDay());
  return Array.from({ length: 7 }, (_, i) => shiftDay(start, i));
}

/**
 * 주간 달력 한 주의 칸들. 오늘 기준 보관 기간(KEEP_DAYS) 밖의 날(expired)과 아직 오지 않은 날(future)은 누를 수 없다.
 * @param {string} today 오늘 YYYY-MM-DD(한국 시간)
 * @param {number} [weekOffset] 0=이번 주, 1=지난 주
 * @returns {{ date: string, day: number, weekday: string, isToday: boolean, state: "open" | "future" | "expired" }[]}
 */
export function calendarWeek(today, weekOffset = 0) {
  const oldest = shiftDay(today, -(KEEP_DAYS - 1));
  return weekDates(today, weekOffset).map((date, i) => ({
    date,
    day: Number(date.slice(8)),
    weekday: WEEKDAYS[i],
    isToday: date === today,
    state: date > today ? "future" : date < oldest ? "expired" : "open",
  }));
}

/**
 * 한 주의 제목("11/1 ~ 11/7").
 * @param {{ date: string }[]} week calendarWeek 의 결과
 * @returns {string}
 */
export function weekTitle(week) {
  const md = (d) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`;
  return `${md(week[0].date)} ~ ${md(week[6].date)}`;
}
