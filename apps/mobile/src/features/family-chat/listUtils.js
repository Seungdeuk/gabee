// 소통 탭 목록 순수 함수(화면과 분리해 시험한다). 대화 글자는 어디에도 기록하지 않는다.
import { formatTime, parseTime } from "./chatUtils";

const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/**
 * 채팅 목록의 시각: 오늘이면 "오후 3:20", 어제면 "어제", 그 외 "10월 21일".
 * @param {string} iso
 * @param {Date} [now]
 * @returns {string}
 */
export function formatRoomTime(iso, now = new Date()) {
  const d = parseTime(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (sameDay(d, now)) return formatTime(iso);
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(d, yesterday)) return "어제";
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/**
 * 접근성 라벨.
 * @param {string} last 마지막 메시지 미리보기
 * @returns {string}
 */
export const roomA11yLabel = (last) => `가족 채팅방, 마지막 메시지 ${last}`;

/**
 * 방 이름 검색 필터(공백 무시, 빈 검색어는 모두 통과).
 * @param {string} name
 * @param {string} query
 * @returns {boolean}
 */
export function matchesQuery(name, query) {
  const q = String(query ?? "").trim();
  return !q || String(name ?? "").includes(q);
}
