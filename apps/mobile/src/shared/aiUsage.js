/** 사용한 비율이 이 값 이상이면 게이지를 "거의 다 썼어요" 상태로 보인다. */
export const USAGE_HIGH_RATIO = 0.8;

/**
 * 한도 대비 사용한 비율(0~1). 한도·사용량을 모르거나 한도가 0 이하이면 null.
 * @param {unknown} limit 하루 한도
 * @param {unknown} used 오늘 쓴 횟수
 * @returns {number | null}
 */
export function usedRatio(limit, used) {
  if (!Number.isFinite(limit) || limit <= 0 || !Number.isFinite(used)) return null;
  return Math.min(1, Math.max(0, used / limit));
}

/**
 * 오늘 사용량 게이지 항목(나, 가족). 횟수는 보이지 않고 사용한 퍼센트만 쓴다. 비율을 모르면 빈 배열.
 * @param {{ userUsed: number | null, groupUsed: number | null }} ratios usedRatio 결과 두 개
 * @returns {{ key: "me" | "family", label: string, ratio: number, percent: number, high: boolean }[]}
 */
export function usageGauges({ userUsed, groupUsed }) {
  if (userUsed === null || groupUsed === null) return [];
  const item = (key, label, ratio) => ({ key, label, ratio, percent: Math.round(ratio * 100), high: ratio >= USAGE_HIGH_RATIO });
  return [item("me", "나", userUsed), item("family", "가족", groupUsed)];
}
