/**
 * 안 읽은 개수를 숫자로 받는다. 못 불러오거나 값이 이상하면 0(배지만 숨기고 화면은 깨뜨리지 않는다).
 * @param {Promise<{ total?: number } | null>} request getUnreadCount() 의 결과
 * @returns {Promise<number>}
 */
export async function safeTotal(request) {
  try {
    const result = await request;
    return Number.isInteger(result?.total) && result.total > 0 ? result.total : 0;
  } catch {
    return 0;
  }
}

/**
 * 종 아이콘 배지 글자. 0 이하면 null(배지를 숨긴다), 100 이상은 "99+".
 * @param {number} total
 * @returns {string | null}
 */
export function badgeLabel(total) {
  if (!(total > 0)) return null;
  return total >= 100 ? "99+" : String(total);
}

/**
 * 알림 시각 표시: 방금·N분 전·N시간 전·N일 전, 일주일이 넘으면 "M월 D일". 읽을 수 없으면 "".
 * 시간대 표시가 없는 값(임시 SQLite)은 UTC 로 본다.
 * @param {string} iso 서버가 준 시각
 * @param {Date} [now]
 * @returns {string}
 */
export function relativeTime(iso, now = new Date()) {
  const text = typeof iso === "string" && !/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? `${iso}Z` : iso;
  const then = new Date(text);
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60000);
  if (minutes < 1) return "방금";
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}일 전`;
  return `${then.getMonth() + 1}월 ${then.getDate()}일`;
}
