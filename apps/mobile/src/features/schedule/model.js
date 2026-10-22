import { KIND } from "./constants";

/**
 * @typedef {Object} Member
 * @property {string} id
 * @property {string} name
 * @property {boolean} hasAccount 계정이 있는 가족 구성원(공유 대상이 될 수 있음)
 */

/**
 * @typedef {Object} Topic
 * @property {string} id
 * @property {string} name
 * @property {"rose" | "amber"} color 제목 옆 글자색 (constants 의 TOPIC_TEXT 키)
 */

/**
 * @typedef {Object} ScheduleItem
 * @property {string} id
 * @property {"appointment" | "todo"} kind
 * @property {string} title
 * @property {string} date "YYYY-MM-DD" (약속·할 일 모두 필수)
 * @property {string | null} startTime "HH:mm", 시간은 선택
 * @property {string | null} endTime
 * @property {boolean} allDay
 * @property {string} place 직접 입력한 글자
 * @property {string} memo
 * @property {string[]} whoIds 누구(나 말고 관련된 사람). 비어 있으면 내 일정
 * @property {string | null} topicId 비어 있으면 분류 없음
 * @property {string[]} sharedWith 공유 대상(가족 구성원 id). 비어 있으면 나만
 * @property {string} createdBy 만든 사람 id
 * @property {boolean} checked 약속은 확인, 할 일은 완료
 */

/**
 * 카드 정렬 순서. 약속 먼저(종일 → 시간순), 그다음 할 일(시간순, 시간 없는 것은 마지막).
 * @param {ScheduleItem} a
 * @param {ScheduleItem} b
 * @returns {number}
 */
export function compareItems(a, b) {
  if (a.kind !== b.kind) return a.kind === KIND.appointment ? -1 : 1;
  const rank = (item) => (item.allDay ? 0 : item.startTime ? 1 : 2);
  if (a.kind === KIND.appointment) {
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
  } else if ((a.startTime === null) !== (b.startTime === null)) {
    return a.startTime === null ? 1 : -1;
  }
  return (a.startTime ?? "").localeCompare(b.startTime ?? "");
}

/**
 * 누구가 비어 있으면 만든 사람 본인으로 본다 (저장 값은 바꾸지 않는다). 필터·에이전트 조회용.
 * @param {ScheduleItem} item
 * @returns {string[]}
 */
export function effectiveWhoIds(item) {
  return item.whoIds.length > 0 ? item.whoIds : [item.createdBy];
}

/**
 * 이름표로 보여줄 글자. 엄마+아빠는 "부모님"으로 합치고, 비어 있으면 이름표가 없다.
 * @param {string[]} whoIds
 * @param {Member[]} members
 * @returns {string[]}
 */
export function whoLabels(whoIds, members) {
  const nameOf = (id) => members.find((m) => m.id === id)?.name ?? "";
  const hasParents = whoIds.includes("mom") && whoIds.includes("dad");
  const rest = hasParents ? whoIds.filter((id) => id !== "mom" && id !== "dad") : whoIds;
  const names = rest.map(nameOf).filter(Boolean);
  return hasParents ? ["부모님", ...names] : names;
}

/**
 * 누구·주제 필터. 같은 줄은 "또는", 줄끼리는 "그리고", 비어 있으면 전체.
 * @param {ScheduleItem[]} items
 * @param {{ whoIds: string[], topicIds: string[] }} filter
 * @returns {ScheduleItem[]}
 */
export function applyFilter(items, { whoIds, topicIds }) {
  return items.filter((item) => {
    const whoOk = whoIds.length === 0 || effectiveWhoIds(item).some((id) => whoIds.includes(id));
    const topicOk = topicIds.length === 0 || (item.topicId !== null && topicIds.includes(item.topicId));
    return whoOk && topicOk;
  });
}
