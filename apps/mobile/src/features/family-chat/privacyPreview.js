/**
 * 분석 결과 아래에 보이는 "가려서 보낸 개수" 한 줄의 순수 함수. 응답 `meta.privacy` 를 문구로 바꾼다.
 * (예전 "AI에 보내기 전 확인 카드"는 없어졌고, 이 파일에는 결과 화면에서 쓰는 부분만 남았다.)
 * 대화 글자·가명화된 텍스트는 여기서 로그에 남기지 않는다.
 */

/** 0 보다 큰 정수만 센다. */
const countOf = (n) => (Number.isFinite(n) && n > 0 ? Math.floor(n) : 0);

/**
 * 가려진 값의 총 개수.
 * @param {Record<string, number> | null | undefined} masked 종류별 가린 개수
 * @returns {number}
 */
export function maskedTotal(masked) {
  if (!masked || typeof masked !== "object") return 0;
  return Object.values(masked).reduce((sum, n) => sum + countOf(n), 0);
}

/**
 * 결과 아래 한 줄: 가린 개수·제외한 메시지 수. 둘 다 0 이거나 정보가 없으면 빈 문자열(생략).
 * @param {{ masked?: Record<string, number>, blocked_messages?: number } | null | undefined} privacy 응답 meta.privacy
 * @returns {string}
 */
export function privacyCaption(privacy) {
  if (!privacy) return "";
  const masked = maskedTotal(privacy.masked);
  const blocked = countOf(privacy.blocked_messages);
  if (masked > 0 && blocked > 0) return `개인정보 ${masked}개를 가려서 보냈고 메시지 ${blocked}개는 제외했어요`;
  if (masked > 0) return `개인정보 ${masked}개를 가려서 보냈어요`;
  if (blocked > 0) return `메시지 ${blocked}개는 제외하고 보냈어요`;
  return "";
}
