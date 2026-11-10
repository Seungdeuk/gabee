// AI 대화 분석 후보의 "이미 등록·보냄" 표시를 다시 분석해도 이어 가기 위한 식별자와 기록(앱을 켜 둔 동안만, 저장소에 남기지 않는다).

/**
 * 후보의 내용으로 만든 식별자. 같은 내용의 후보는 다시 분석해도 같은 식별자가 나온다(순번이 아니다).
 * @param {"schedule" | "todo"} kind
 * @param {Record<string, unknown> | null | undefined} candidate 분석 응답의 일정·할 일 후보
 * @returns {string}
 */
export function candidateKey(kind, candidate) {
  const entries = Object.entries(candidate ?? {})
    .filter(([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v) || Array.isArray(v))
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `${kind}:${JSON.stringify(entries)}`;
}

const done = new Set();

/**
 * 이 후보를 등록하거나 보냈다고 기록한다.
 * @param {string} key candidateKey 결과
 */
export function markCandidateDone(key) {
  done.add(key);
}

/**
 * 이 후보가 이미 등록되었거나 보내졌는지.
 * @param {string} key candidateKey 결과
 * @returns {boolean}
 */
export const isCandidateDone = (key) => done.has(key);

/** 기록을 모두 지운다(시험용). */
export function resetCandidateDone() {
  done.clear();
}
