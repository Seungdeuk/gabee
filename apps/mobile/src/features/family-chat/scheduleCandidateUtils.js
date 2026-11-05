// 대화 분석의 일정 후보에서 AI 가 정하지 못한 날짜·시간을 사용자가 채워 등록할 수 있게 하는 순수 함수(시험: tests/schedulecandidate.test.js)
// 없는 값은 지어내지 않는다: 후보에 이미 있는 값은 그대로 두고, 빠진 값만 사용자가 입력한 것으로 채운다.

import { dayFromChip } from "./togetherUtils";

/**
 * 시간 입력칸에 적는 글자를 숫자만 남겨 HH:MM 모양으로 다듬는다(두 자리를 치면 콜론이 자동으로 붙는다).
 * @param {string | null | undefined} text
 * @returns {string}
 */
export function formatTimeInput(text) {
  const digits = String(text ?? "").replace(/\D/g, "").slice(0, 4);
  return digits.length <= 2 ? digits : `${digits.slice(0, 2)}:${digits.slice(2)}`;
}

/**
 * 00:00~23:59 의 HH:MM 인지.
 * @param {unknown} value
 * @returns {boolean}
 */
export function isTime(value) {
  return typeof value === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

/**
 * 후보에서 사용자가 채워야 하는 부분(날짜·시간이 비어 있는지).
 * @param {{ date?: string | null, time?: string | null } | null | undefined} candidate
 * @returns {{ date: boolean, time: boolean }}
 */
export function scheduleCandidateNeeds(candidate) {
  return { date: !candidate?.date, time: !candidate?.time };
}

/**
 * 후보의 빠진 날짜·시간을 사용자 입력으로 채운 새 후보를 만든다(원래 후보는 바꾸지 않는다). 후보에 이미 있는 값은 덮어쓰지 않는다.
 * 날짜는 칩(오늘·내일)이나 직접 입력(YYYY-MM-DD, 실제 있는 날이고 오늘 이후)에서, 시간은 HH:MM 입력에서 가져온다.
 * 올바르지 않은 입력은 채우지 않아 canRegisterSchedule 이 false 로 남는다.
 * @param {{ title?: string, date?: string | null, time?: string | null, place?: string | null }} candidate
 * @param {{ day?: string | null, customText?: string, timeText?: string }} [input] day 는 DAY_CHIPS 의 key
 * @param {Date} [now]
 * @returns {{ title?: string, date: string | null, time: string | null, place?: string | null }}
 */
export function completeScheduleCandidate(candidate, input = {}, now = new Date()) {
  const date = candidate?.date || dayFromChip(input.day, now, input.customText ?? null);
  const time = candidate?.time || (isTime(input.timeText) ? input.timeText : null);
  return { ...candidate, date: date ?? null, time: time ?? null };
}

/**
 * 같은 후보를 한 번에 한 번만 등록하도록 후보 식별자를 잡는다. 이미 잡혀 있으면 false(빠르게 두 번 눌러도 요청이 한 번만 나간다).
 * @param {Set<string>} busy 등록 중이거나 등록된 후보 식별자 모음
 * @param {string} key candidateKey
 * @returns {boolean}
 */
export function claimCandidate(busy, key) {
  if (busy.has(key)) return false;
  busy.add(key);
  return true;
}

/**
 * 등록에 실패했을 때 후보를 놓아 다시 시도할 수 있게 한다.
 * @param {Set<string>} busy
 * @param {string} key
 */
export function releaseCandidate(busy, key) {
  busy.delete(key);
}
