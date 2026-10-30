import { KIND } from "./constants";
import { compareItems } from "./model";
import { formatYearMonth } from "./utils/date";

/** 달력 점의 최대 개수 (날짜당). */
const MAX_DOTS = 3;

export { whoChips } from "./filter";

/**
 * 날짜별 점 개수. 약속과 할 일을 따로 센다.
 * @param {import("./model").ScheduleItem[]} items
 * @returns {Map<string, { appointment: number, todo: number }>}
 */
export function buildMarks(items) {
  const marks = new Map();
  items.forEach((item) => {
    const mark = marks.get(item.date) ?? { appointment: 0, todo: 0 };
    mark[item.kind] += 1;
    marks.set(item.date, mark);
  });
  return marks;
}

/**
 * 한 날짜에 찍을 점 종류. 약속 먼저, 최대 3개.
 * @param {{ appointment: number, todo: number } | undefined} mark
 * @returns {("appointment" | "todo")[]}
 */
export function dotsFor(mark) {
  if (!mark) return [];
  const appointments = Math.min(mark.appointment, MAX_DOTS);
  const todos = Math.min(mark.todo, MAX_DOTS - appointments);
  return [...Array(appointments).fill(KIND.appointment), ...Array(todos).fill(KIND.todo)];
}

/**
 * 한 날짜의 항목. 약속 먼저(종일 → 시간순), 그다음 할 일.
 * @param {import("./model").ScheduleItem[]} items
 * @param {string} date "YYYY-MM-DD"
 * @returns {import("./model").ScheduleItem[]}
 */
export function itemsOnDate(items, date) {
  return items.filter((item) => item.date === date).sort(compareItems);
}

/**
 * 목록 모드용 시간 구분. 오늘 / 다가오는 것(가까운 날부터) / 지난 것(최근 날부터).
 * @param {import("./model").ScheduleItem[]} items
 * @param {string} today "YYYY-MM-DD"
 * @returns {{ today: import("./model").ScheduleItem[], upcoming: import("./model").ScheduleItem[], past: import("./model").ScheduleItem[] }}
 */
export function splitByTime(items, today) {
  const asc = [...items].sort((a, b) => a.date.localeCompare(b.date) || compareItems(a, b));
  const desc = [...items].sort((a, b) => b.date.localeCompare(a.date) || compareItems(a, b));
  return {
    today: asc.filter((item) => item.date === today),
    upcoming: asc.filter((item) => item.date > today),
    past: desc.filter((item) => item.date < today),
  };
}

/**
 * 월 구분선용으로 순서를 지킨 채 같은 달끼리 묶는다.
 * @param {import("./model").ScheduleItem[]} items 날짜순으로 정렬된 항목
 * @returns {{ key: string, label: string, items: import("./model").ScheduleItem[] }[]}
 */
export function groupByMonth(items) {
  const groups = [];
  items.forEach((item) => {
    const key = item.date.slice(0, 7);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(item);
    else groups.push({ key, label: formatYearMonth(item.date), items: [item] });
  });
  return groups;
}
