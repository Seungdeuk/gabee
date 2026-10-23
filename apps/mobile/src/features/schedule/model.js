import { KIND } from "./constants";
import { addMinutes } from "./utils/time";

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
 * 누구 칩 "parents"(부모님)는 엄마와 아빠가 모두 들어 있는 항목에 맞는다.
 * @param {ScheduleItem[]} items
 * @param {{ whoIds: string[], topicIds: string[] }} filter
 * @returns {ScheduleItem[]}
 */
export function applyFilter(items, { whoIds, topicIds }) {
  const matches = (item, chipId) => {
    const ids = effectiveWhoIds(item);
    return chipId === "parents" ? ids.includes("mom") && ids.includes("dad") : ids.includes(chipId);
  };
  return items.filter((item) => {
    const whoOk = whoIds.length === 0 || whoIds.some((chipId) => matches(item, chipId));
    const topicOk = topicIds.length === 0 || (item.topicId !== null && topicIds.includes(item.topicId));
    return whoOk && topicOk;
  });
}

/**
 * 같이(함께 해 달라는 요청) 하나. 보낸 사람이 정한 내용·날짜·시간·장소·메모와 받는 사람별 답을 담는다.
 * @typedef {Object} TogetherRequest
 * @property {string} id
 * @property {string} fromId 보낸 사람 id
 * @property {string[]} toIds 받는 사람 id(1명 이상)
 * @property {string} title 내용
 * @property {string} date "YYYY-MM-DD"
 * @property {string | null} startTime
 * @property {string | null} endTime
 * @property {boolean} allDay
 * @property {string} place
 * @property {string} memo
 * @property {string[]} whoIds 누구(관련된 사람, 선택). 받는 사람 일정의 이름표가 된다
 * @property {Record<string, "accepted" | "declined">} replies 받는 사람별 답. 답이 없으면 기다리는 중
 * @property {boolean} cancelled 보낸 사람이 답을 기다리는 동안 취소했는지
 * @property {string | null} [itemId] 내가 수락해서 만든 내 일정의 id. 답을 바꾸면 이 일정을 지운다
 */

/**
 * 보낸 사람이 보는 상태. 취소했으면 "cancelled", 한 명이라도 수락했으면 "accepted", 아니면 "pending".
 * "어렵겠어요"는 보낸 사람에게 알리지 않으므로 상태에 반영하지 않는다.
 * @param {TogetherRequest} request
 * @returns {"cancelled" | "accepted" | "pending"}
 */
export function sentStatus(request) {
  if (request.cancelled) return "cancelled";
  return Object.values(request.replies).includes("accepted") ? "accepted" : "pending";
}

/**
 * 받은 사람이 보는 상태. 내가 답했으면 그 답("accepted" | "declined"), 아니면 "pending".
 * @param {TogetherRequest} request
 * @param {string} meId 나의 id
 * @returns {"pending" | "accepted" | "declined"}
 */
export function receivedStatus(request, meId) {
  return request.replies[meId] ?? "pending";
}

/**
 * 같은 날 시간이 겹치는 내 일정 하나. 종일이거나 시간이 없는 쪽은 겹침으로 보지 않는다. 끝 시간이 없으면 한 시간짜리로 본다.
 * @param {ScheduleItem[]} items
 * @param {{ date: string, allDay: boolean, startTime: string | null, endTime: string | null }} request
 * @returns {ScheduleItem | undefined}
 */
export function findConflict(items, request) {
  if (request.allDay || !request.startTime) return undefined;
  const end = (time, endTime) => endTime ?? addMinutes(time, 60);
  const requestEnd = end(request.startTime, request.endTime);
  return items.find(
    (item) =>
      item.date === request.date &&
      !item.allDay &&
      item.startTime !== null &&
      item.startTime < requestEnd &&
      request.startTime < end(item.startTime, item.endTime),
  );
}
