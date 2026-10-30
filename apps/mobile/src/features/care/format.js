const pad = (n) => String(n).padStart(2, "0");

/** @param {string} hhmm "HH:MM" @returns {number} 자정부터의 분 */
export const toMinutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));

/** @param {number} m 분(0 이상) @returns {string} 예: 45분, 1시간 20분 */
export const hm = (m) => (m >= 60 ? `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""}` : `${m}분`);

/** 예정 시각까지 남은 분을 말로 바꾼다. @param {number} minutes 지났으면 음수 @returns {string} 예: 40분 후, 지금, 20분 지났어요 */
export const untilText = (minutes) => (minutes > 0 ? `${hm(minutes)} 후` : minutes === 0 ? "지금" : `${hm(-minutes)} 지났어요`);

/** @param {number} minutes 예정 시각이 지난 분 @returns {string} 예: 3시간 전 */
export const agoText = (minutes) => `${hm(Math.max(0, minutes))} 전`;

/**
 * 데일리 체크에서 식사 항목(meal_type 이 있는 항목)을 뺀다. 서버는 아침·점심·저녁 식사를 기본 체크 항목으로 계속 내려 주지만,
 * 식단 기능을 화면에서 뺐으므로 목록·진행 수·누락 알림에서 보이지 않게 한다(서버 데이터는 그대로).
 * @param {import("./api").Daily} daily
 * @returns {import("./api").Daily}
 */
export function withoutMealItems(daily) {
  const hidden = new Set(daily.items.filter((i) => i.meal_type).map((i) => i.id));
  if (hidden.size === 0 && (daily.meals ?? []).length === 0) return daily;
  const keep = (ids) => ids.filter((id) => !hidden.has(id));
  return {
    ...daily,
    items: daily.items.filter((i) => !hidden.has(i.id)),
    meals: [],
    missing_ids: keep(daily.missing_ids),
    upcoming_ids: keep(daily.upcoming_ids),
    cleanup_ids: keep(daily.cleanup_ids),
    skipped_ids: keep(daily.skipped_ids),
    done_ids: keep(daily.done_ids),
  };
}

export { pad };
