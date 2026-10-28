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
