// 데일리 체크 서버 응답 ↔ 화면 모양 변환(순수 함수). api.js 가 쓰고, 시험은 tests/schedule_daily_server.test.js.
// 서버 규칙: 습관 kind 1 = 한 번 체크, 2 = 횟수. repeat_days = 월~일 1/0 일곱 글자. 응원 kind 1·2·3 = 사랑해요·최고예요·잘하셨어요.
// 시각은 서버가 시간대가 붙은 ISO 로 준다. 화면은 한국 시간의 날짜 키("YYYY-MM-DD")와 "HH:MM" 으로 쓴다.
import { ALL_DAYS, WEEK_DAYS } from "./logic";

const DAY_KEYS = WEEK_DAYS.map((d) => d.key);
const KST_MS = 9 * 60 * 60 * 1000;
const pad = (n) => String(n).padStart(2, "0");

export const KIND_TO_SERVER = { check: 1, count: 2 };
export const KIND_FROM_SERVER = { 1: "check", 2: "count" };
export const CHEER_KIND_TO_SERVER = { love: 1, best: 2, well: 3 };
export const CHEER_KIND_FROM_SERVER = { 1: "love", 2: "best", 3: "well" };

/** 서버 시각 문자열(또는 Date, 숫자)을 밀리초로. 시간대가 없으면 UTC 로 본다. 소수점 넷째 자리 이하는 버린다(기기마다 읽는 방식이 달라서). */
export function toMs(value) {
  if (value instanceof Date) return value.getTime();
  if (typeof value === "number") return value;
  let text = String(value).replace(/(\.\d{3})\d+/, "$1");
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += "Z";
  return new Date(text).getTime();
}

/** 한국 시간으로 옮긴 Date(값을 읽을 때는 getUTC* 를 쓴다). */
const kstShift = (value) => new Date(toMs(value) + KST_MS);

/** 한국 시간 날짜 키 "YYYY-MM-DD". */
export function kstDateKey(value) {
  const d = kstShift(value);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/** 한국 시간 "HH:MM". */
export function kstClock(value) {
  const d = kstShift(value);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** 오늘(한국 시간) 날짜 키. 서버의 "오늘"과 맞추려고 기기 시간대와 상관없이 한국 시간을 쓴다. */
export function todayKeyKST(now = Date.now()) {
  return kstDateKey(now);
}

/** repeat_days("1011100") → 요일 키 배열(월~일 순서). */
export function repeatToDays(repeat) {
  return DAY_KEYS.filter((_, i) => repeat?.[i] === "1");
}

/** 요일 키 배열 → repeat_days 일곱 글자(월~일). */
export function daysToRepeat(days) {
  return DAY_KEYS.map((key) => (days.includes(key) ? "1" : "0")).join("");
}

/**
 * 서버 기록(요청한 날짜의 줄) → 화면의 entry. 날짜 유효성은 서버가 이미 반영해 보낸다(줄이 없는 날은 미완료·0).
 * 한 번 체크는 done, 횟수는 count 와 confirmed(목표 도달)를 쓴다. doneAt 은 완료 시각("HH:MM", 한국 시간).
 */
export function entryFromServer(row) {
  const doneAt = row.confirmed_at ? kstClock(row.confirmed_at) : null;
  if (row.kind === 2) {
    return { done: Boolean(row.confirmed), count: row.count ?? 0, doneAt: row.confirmed ? doneAt : null };
  }
  return { done: Boolean(row.done), count: 0, doneAt: row.done ? doneAt : null };
}

/** 서버 메모 → 화면 메모({ note, noteShared }). 메모가 없으면 undefined. */
export function memoFromServer(row) {
  return row.note ? { note: row.note, noteShared: Boolean(row.note_shared) } : undefined;
}

/**
 * 서버 습관 한 줄 → 화면 항목. notify 는 화면의 alarm 과 같은 값이다.
 * entry·memo 는 요청한 날짜(없으면 오늘)의 기록과 메모다. applies 는 그 날짜 목록에 나올지(서버가 계산한 값)다.
 * updatedAt 은 습관 정의가 바뀐 시각이다. 반복 요일을 바꾼 시각(repeat_updated_at)은 서버 안에서만 쓰고 응답에 없다(목록 거르기는 applies 로 한다).
 */
export function itemFromServer(row) {
  const type = KIND_FROM_SERVER[row.kind] ?? "check";
  const count = type === "count";
  return {
    id: row.id,
    name: row.name,
    type,
    goal: count ? (row.goal ?? 1) : 1,
    unit: count ? (row.unit ?? "") : "",
    days: repeatToDays(row.repeat_days),
    alarm: Boolean(row.notify),
    shareWithFamily: Boolean(row.shared),
    position: row.position ?? 0,
    entry: entryFromServer(row),
    memo: memoFromServer(row),
    applies: Boolean(row.applies),
    updatedAt: row.updated_at ?? null,
  };
}

/** 화면 항목 → 서버 습관 본문(만들기·고치기 공용). 한 번 체크는 목표·단위를 보내지 않는다. */
export function itemToServer(item) {
  const count = item.type === "count";
  return {
    name: item.name,
    kind: count ? KIND_TO_SERVER.count : KIND_TO_SERVER.check,
    goal: count ? item.goal : null,
    unit: count ? (item.unit ?? "") : "",
    repeat_days: daysToRepeat(item.days ?? []),
    shared: Boolean(item.shareWithFamily),
    notify: Boolean(item.alarm),
  };
}

/** 기록 저장 본문: 한 번 체크는 done, 횟수는 count(절대값). 메모는 따로 보낸다(noteToServer). */
export function entryToServer(item, entry) {
  if (item.type === "count") return { count: entry?.count ?? 0 };
  return { done: Boolean(entry?.done) };
}

/** 메모 저장 본문({ note, note_shared }). memo 가 없으면 지우기다: note 를 null 로 보낸다(서버는 빈 글자와 null 을 모두 지운다). */
export function noteToServer(memo) {
  return memo ? { note: memo.note, note_shared: Boolean(memo.noteShared) } : { note: null, note_shared: false };
}

/**
 * 가족이 보는 습관 한 줄(서버는 오늘 요일에 해당하고 shared 인 것만 준다). 화면에서는 오늘 목록으로 그대로 쓴다.
 * note 는 서버가 공개로 준 메모 글자(없으면 null)다. 가족 탭은 이 글자만 보여 준다.
 */
export function memberItemFromServer(row) {
  const type = KIND_FROM_SERVER[row.kind] ?? "check";
  const count = type === "count";
  return {
    id: row.id,
    name: row.name,
    type,
    goal: count ? (row.goal ?? 1) : 1,
    unit: count ? (row.unit ?? "") : "",
    days: [...ALL_DAYS],
    alarm: false,
    shareWithFamily: true,
    entry: entryFromServer(row),
    note: row.note ?? null,
  };
}

/** 응원 한 장 → 화면 모양. direction 은 호출한 쪽이 정한 방향(received | sent). 날짜·시각은 한국 시간(sent_at 기준). */
export function cheerFromServer(row, direction) {
  return {
    id: row.id,
    direction,
    fromName: row.from_name ?? "",
    toName: row.to_name ?? "",
    kind: CHEER_KIND_FROM_SERVER[row.kind] ?? "love",
    text: row.message ?? "",
    date: kstDateKey(row.sent_at),
    time: kstClock(row.sent_at),
    thanked: Boolean(row.thanked_at),
    closed: Boolean(row.closed),
    groupChat: Boolean(row.chat_left),
  };
}

/** 가족 요약 한 줄 → { id(앱 id), name, done, total }. toApp 은 가족 변환기(store 의 ready() 가 준 것). */
export function summaryFromServer(row, toApp) {
  return { id: toApp(row.user_id) ?? row.user_id, name: row.name, total: row.total, done: row.done };
}

/** 서버 오류 → 빈 상태 글자(목록 불러오기 실패). 503 은 기능 준비 중(스키마 미적용)이다. */
export function loadErrorText(error) {
  return error?.status === 503 ? "준비 중이에요" : "서버에 연결하지 못했어요";
}

/** 서버 오류 → 안내 팝업 내용(저장·지우기·보내기 실패). title 은 호출한 쪽이 정한다. */
export function failureNotice(error, title = "저장하지 못했어요") {
  if (error?.status === 503) return { title: "준비 중이에요", body: "잠시 후 다시 해 주세요" };
  // 400 은 서버가 이유를 글로 준다(예: 7일 전보다 이른 날짜, 습관을 만들기 전 날짜)
  if (error?.status === 400 && error.message) return { title, body: error.message };
  // 422 는 입력 모양·글자 수가 서버 상한을 넘은 것이다(화면의 입력 제한으로 대부분 막힌다)
  if (error?.status === 422) return { title, body: "입력한 글자 수를 확인해 주세요" };
  return { title, body: "잠시 후 다시 해 주세요" };
}
