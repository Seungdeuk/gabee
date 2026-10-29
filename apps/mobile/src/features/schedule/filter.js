// 일정 대상(나·공동·구성원) 구분과 필터. 화면 라이브러리를 불러오지 않는 순수 함수라 노드 시험에서 바로 쓴다.

/**
 * 공동 일정인가. 서버가 알려 준 값이 있으면 그것을, 없으면(mock) 공유 대상이 있거나 남이 만든 일정이면 공동으로 본다.
 * @param {import("./model").ScheduleItem} item
 * @returns {boolean}
 */
export function isShared(item) {
  return item.shared ?? (item.sharedWith.length > 0 || item.createdBy !== "me");
}

/**
 * 이 일정으로 나와 얽힌 사람(나 제외). 공동 필터에서 구성원 칩을 고를 때 쓴다.
 * @param {import("./model").ScheduleItem} item
 * @returns {string[]}
 */
export function involvedIds(item) {
  if (item.sharedIds) return item.sharedIds;
  return [...new Set([...item.sharedWith, ...(item.createdBy !== "me" ? [item.createdBy] : [])])].filter((id) => id !== "me");
}

/**
 * 대상·주제 필터. 같은 줄은 "또는", 줄끼리는 "그리고", 비어 있으면 전체.
 * 대상 칩: "me"(나)는 나 혼자 일정, "shared"(공동)는 공동 일정, 구성원 칩은 그 사람과 얽힌 공동 일정.
 * @param {import("./model").ScheduleItem[]} items
 * @param {{ whoIds: string[], topicIds: string[] }} filter
 * @returns {import("./model").ScheduleItem[]}
 */
export function applyFilter(items, { whoIds, topicIds }) {
  const matches = (item, chipId) => {
    if (chipId === "me") return !isShared(item);
    if (chipId === "shared") return isShared(item);
    return isShared(item) && involvedIds(item).includes(chipId);
  };
  return items.filter((item) => {
    const whoOk = whoIds.length === 0 || whoIds.some((chipId) => matches(item, chipId));
    const topicOk = topicIds.length === 0 || (item.topicId !== null && topicIds.includes(item.topicId));
    return whoOk && topicOk;
  });
}

/**
 * "대상" 칩 목록: 나(나 혼자 일정) · 공동(공유한·공유받은 일정) · 가족 구성원(그 사람과 얽힌 공동 일정, 별명 → 이름).
 * @param {import("./model").Member[]} members
 * @returns {{ id: string, label: string }[]}
 */
export function whoChips(members) {
  return [
    { id: "me", label: "나" },
    { id: "shared", label: "공동" },
    ...members.filter((m) => m.id !== "me").map((m) => ({ id: m.id, label: m.name })),
  ];
}
