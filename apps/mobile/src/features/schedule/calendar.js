import { KIND } from "./constants";
import { compareItems } from "./model";

/** 달력 점의 최대 개수 (날짜당). */
const MAX_DOTS = 3;

/**
 * "누구" 칩 목록. 가족 구성원 + 엄마·아빠를 합친 "부모님".
 * @param {import("./model").Member[]} members
 * @returns {{ id: string, label: string }[]}
 */
export function whoChips(members) {
  const chips = members.map((m) => ({ id: m.id, label: m.name }));
  const hasParents = members.some((m) => m.id === "mom") && members.some((m) => m.id === "dad");
  return hasParents ? [...chips, { id: "parents", label: "부모님" }] : chips;
}

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
