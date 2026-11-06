/**
 * 여행 모드(일시정지) 기간 선택의 순수 계산. 서버는 1~14일만 받는다.
 */
export const PAUSE_OPTIONS = [
  { key: "1", label: "1일" },
  { key: "3", label: "3일" },
  { key: "7", label: "7일" },
  { key: "other", label: "기타" },
];
export const MIN_PAUSE_DAYS = 1;
export const MAX_PAUSE_DAYS = 14;

/**
 * 고른 기간(1일·3일·7일·기타)에서 멈출 일수를 구한다. 기타는 사용자가 적은 값을 읽고 1~14 의 정수가 아니면 오류 문구를 돌려준다.
 * @param {string} key PAUSE_OPTIONS 의 key
 * @param {string} custom 기타에서 적은 글
 * @returns {{ days: number | null, error: string }}
 */
export function pauseDays(key, custom) {
  if (key !== "other") return { days: Number(key), error: "" };
  const text = String(custom ?? "").trim();
  if (!text) return { days: null, error: "며칠 동안 멈출지 적어 주세요" };
  if (!/^\d+$/.test(text)) return { days: null, error: "숫자만 적어 주세요" };
  const days = Number(text);
  if (days < MIN_PAUSE_DAYS || days > MAX_PAUSE_DAYS) {
    return { days: null, error: `${MIN_PAUSE_DAYS}~${MAX_PAUSE_DAYS}일 사이로 적어 주세요` };
  }
  return { days, error: "" };
}
