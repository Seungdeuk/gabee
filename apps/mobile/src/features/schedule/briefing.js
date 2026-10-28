import { addDays, formatMonthDay } from "./utils/date";

// 일정 메인 브리핑(고른 날짜와 그 다음 날)의 구역 이름. 화면에 의존하지 않아 node 테스트로 확인한다.

/** 오늘·내일·어제는 말로 쓰고 날짜를 덧붙이며, 그 밖은 날짜만 쓴다. */
function named(key, today) {
  const date = formatMonthDay(key);
  if (key === today) return "오늘";
  if (key === addDays(today, 1)) return `내일 · ${date}`;
  if (key === addDays(today, -1)) return `어제 · ${date}`;
  return null;
}

/**
 * 고른 날짜와 그 다음 날의 구역 이름. 오늘을 고르면 예전처럼 "오늘" / "내일 · 10월 29일"이다.
 * 다른 날을 고르면 그 날은 날짜로("10월 29일"), 다음 날은 "다음 날 · 10월 30일"로 보인다.
 * @param {string} selected "YYYY-MM-DD"
 * @param {string} today "YYYY-MM-DD"
 * @returns {[string, string]}
 */
export function briefingLabels(selected, today) {
  const next = addDays(selected, 1);
  return [
    named(selected, today) ?? formatMonthDay(selected),
    named(next, today) ?? `다음 날 · ${formatMonthDay(next)}`,
  ];
}
