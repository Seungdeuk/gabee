import { addDays, todayKey } from "./utils/date";

// 화면 확인용 임시 데이터. 서버 연동 시 api.js로 교체한다.

// 기존 임시 화면(ScheduleScreen)이 쓰는 목록. 메인 화면을 새로 만들 때 함께 지운다.
export const events = [
  { id: "1", when: "오늘 19:00", title: "아버지 안부 전화", note: "지민 담당 · 수진 확인", tone: "blue", icon: "call" },
  { id: "2", when: "내일 14:00", title: "한결의원", note: "어머니 김영희 · 동행 확인", tone: "green", icon: "medkit" },
  { id: "3", when: "10.18 토요일", title: "가족 모임", note: "전원 참석 예정", tone: "orange", icon: "people" },
];

export const ME_ID = "me";

/** @type {import("./model").Member[]} */
export const members = [
  { id: "me", name: "나", hasAccount: true },
  { id: "mom", name: "엄마", hasAccount: true },
  { id: "dad", name: "아빠", hasAccount: true },
];

/** @type {import("./model").Topic[]} */
export const topics = [
  { id: "ceremony", name: "경조사", color: "peach" },
  { id: "hospital", name: "병원", color: "green" },
];

/** 오늘 기준 상대 날짜로 만든 샘플. @returns {import("./model").ScheduleItem[]} */
export function createMockItems() {
  const today = todayKey();
  const base = { place: "", memo: "", whoIds: [], topicId: null, sharedWith: [], createdBy: ME_ID, checked: false };
  return [
    { ...base, id: "s1", kind: "appointment", title: "가족 저녁 식사", date: today, startTime: "19:00", endTime: "20:30", allDay: false, place: "집 앞 식당", sharedWith: ["mom", "dad"] },
    { ...base, id: "s2", kind: "appointment", title: "병원 방문", date: today, startTime: "10:00", endTime: "11:00", allDay: false, place: "한결의원", whoIds: ["mom"], topicId: "hospital", sharedWith: ["mom"], checked: true },
    { ...base, id: "s3", kind: "appointment", title: "가족 모임", date: addDays(today, 1), startTime: null, endTime: null, allDay: true, topicId: "ceremony", sharedWith: ["mom", "dad"] },
    { ...base, id: "s4", kind: "todo", title: "세탁물 찾기", date: today, startTime: "18:00", endTime: null, allDay: false },
    { ...base, id: "s5", kind: "todo", title: "병원 예약하기", date: addDays(today, 1), startTime: null, endTime: null, allDay: false, whoIds: ["dad"], topicId: "hospital", memo: "다음 주 화요일 이후로" },
    { ...base, id: "s6", kind: "appointment", title: "아버지 생신", date: addDays(today, 5), startTime: null, endTime: null, allDay: true, whoIds: ["dad"], topicId: "ceremony", sharedWith: ["mom"], createdBy: "mom" },
    { ...base, id: "s7", kind: "todo", title: "생신 선물 고르기", date: addDays(today, 3), startTime: null, endTime: null, allDay: false, whoIds: ["dad"], topicId: "ceremony" },
    { ...base, id: "s8", kind: "appointment", title: "정기 검진", date: addDays(today, -3), startTime: "09:30", endTime: "10:30", allDay: false, topicId: "hospital", checked: true },
  ];
}
