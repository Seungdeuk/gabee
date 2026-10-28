import { addDays } from "./utils/date";

// 다가오는 항목을 "앞으로 한 달치, 5개씩 더보기"로 줄이는 순수 계산(테마·앱 의존 없이 node 테스트로 시험한다).

/** 앞으로 이 일수(한 달)까지만 보고, 한 번에 이 개수씩 보인다. */
export const UPCOMING_DAYS = 30;
export const PAGE_SIZE = 5;

/**
 * 날짜순으로 정렬된 항목을 앞으로 한 달치로 줄이고, pages × 5개까지만 보인다. 마지막으로 보이는 일정과 같은 날짜의 일정은
 * 개수를 넘어도 모두 포함한다(5개째가 30일이면 30일 일정은 전부). "더보기"를 누를 때마다 pages 를 하나 올린다.
 * @template T
 * @param {T[]} items 날짜순으로 정렬된 항목
 * @param {string} today "YYYY-MM-DD"
 * @param {number} pages 지금까지 펼친 쪽 수(처음 1)
 * @param {{ days?: number, size?: number, dateOf?: (item: T) => string }} [options]
 * @returns {{ shown: T[], remaining: number }} remaining = 한 달 안에서 아직 안 보이는 개수
 */
export function pageUpcoming(items, today, pages = 1, { days = UPCOMING_DAYS, size = PAGE_SIZE, dateOf = (item) => item.date } = {}) {
  const last = addDays(today, days);
  const inRange = items.filter((item) => dateOf(item) <= last);
  const count = Math.max(pages, 1) * size;
  if (inRange.length <= count) return { shown: inRange, remaining: 0 };
  const cutoff = dateOf(inRange[count - 1]);
  const shown = inRange.filter((item) => dateOf(item) <= cutoff);
  return { shown, remaining: inRange.length - shown.length };
}
