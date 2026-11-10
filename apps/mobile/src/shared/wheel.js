/**
 * 휠(세로 스크롤 선택) 스크롤 오프셋을 항목 번호로 바꾼다. 가장 가까운 항목으로 반올림하고 목록 범위로 자른다.
 * @param {number} offset 스크롤 위치(px)
 * @param {number} itemHeight 항목 한 줄 높이(px)
 * @param {number} count 항목 개수
 * @returns {number} 0 이상 count-1 이하의 번호(항목이 없거나 숫자가 아니면 0)
 */
export function offsetToIndex(offset, itemHeight, count) {
  if (!Number.isFinite(offset) || count <= 0) return 0;
  return Math.min(Math.max(Math.round(offset / itemHeight), 0), count - 1);
}

/**
 * 항목 번호가 가운데 줄에 오는 스크롤 위치를 구한다.
 * @param {number} index 항목 번호
 * @param {number} itemHeight 항목 한 줄 높이(px)
 * @returns {number}
 */
export function indexToOffset(index, itemHeight) {
  return index * itemHeight;
}
