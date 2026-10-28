// "자주 쓰는 사람" 칩 줄과 주제 입력 폼의 순수 로직(저장소·화면에 의존하지 않아 node 테스트로 시험한다).

/** 주제 색 5가지(이름 → 글자색은 constants.js 의 TOPIC_TEXT). 첫째가 기본 선택. */
export const TOPIC_COLOR_KEYS = ["rose", "amber", "green", "sky", "purple"];
export const TOPIC_NAME_MAX = 30;

/**
 * 칩 줄에 보일 사람. 빼 둔(hidden) 사람은 빠지지만, 지금 선택돼 있으면 선택 상태 유지를 위해 보인다.
 * @param {{ id: string }[]} all 가족 구성원(나 제외)
 * @param {string[]} hiddenIds
 * @param {string[]} selectedIds
 */
export const visibleMembers = (all, hiddenIds, selectedIds) =>
  all.filter((m) => !hiddenIds.includes(m.id) || selectedIds.includes(m.id));

/** 칩 줄에서 빠져 있어 "+ 누구" 로 다시 꺼낼 수 있는 사람(visibleMembers 의 나머지). */
export const hiddenMembers = (all, hiddenIds, selectedIds) =>
  all.filter((m) => hiddenIds.includes(m.id) && !selectedIds.includes(m.id));

/** 칩 줄에서 뺀다(가족 구성원 자체는 그대로). */
export const hideId = (hiddenIds, id) => (hiddenIds.includes(id) ? hiddenIds : [...hiddenIds, id]);

/** 다시 칩 줄에 넣는다. */
export const showId = (hiddenIds, id) => hiddenIds.filter((x) => x !== id);

/** 지금 가족에 없는 id 를 버린다(가족이 바뀐 경우). */
export const pruneHidden = (hiddenIds, all) => hiddenIds.filter((id) => all.some((m) => m.id === id));

export const serializeHidden = (hiddenIds) => JSON.stringify(hiddenIds);

/** 저장된 글자 → 빼 둔 id 목록. 모양이 이상하면 빈 목록. */
export function restoreHidden(raw) {
  try {
    const list = JSON.parse(raw ?? "[]");
    return Array.isArray(list) ? [...new Set(list.filter((x) => typeof x === "string" && x))] : [];
  } catch {
    return [];
  }
}

/**
 * 주제 이름 검사. 앞뒤 공백을 지우고, 비었거나 30자를 넘으면 추가할 수 없다.
 * @param {string} name
 * @returns {{ ok: boolean, name: string }}
 */
export function validateTopicName(name) {
  const trimmed = String(name ?? "").trim();
  return { ok: trimmed !== "" && trimmed.length <= TOPIC_NAME_MAX, name: trimmed };
}

/** 주제 만들기 실패 → 입력칸 아래에 보여 줄 짧은 말. */
export function topicErrorMessage(error) {
  if (error?.code === "topic_exists") return "이미 있는 주제예요";
  if (error?.code === "invalid_topic") return "주제 이름을 확인해 주세요";
  return "주제를 만들지 못했어요";
}
