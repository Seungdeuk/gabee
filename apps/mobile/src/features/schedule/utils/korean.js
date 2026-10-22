/**
 * 이름 뒤에 붙는 주격 조사. 받침이 있으면 "이", 없으면 "가". 예: 엄마 → "가", 민준 → "이"
 * @param {string} name
 * @returns {"이" | "가"}
 */
export function subjectParticle(name) {
  const code = name.charCodeAt(name.length - 1) - 0xac00;
  const isHangul = code >= 0 && code <= 11171;
  return isHangul && code % 28 !== 0 ? "이" : "가";
}
