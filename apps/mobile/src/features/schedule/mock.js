import { addDays, todayKey } from "./utils/date";

// 화면 확인용 임시 데이터. 서버 연동 시 api.js로 교체한다.

export const ME_ID = "me";

/** @type {import("./model").Member[]} */
export const members = [
  { id: "me", name: "나", hasAccount: true },
  { id: "mom", name: "엄마", hasAccount: true },
  { id: "dad", name: "아빠", hasAccount: true },
];

/** @type {import("./model").Topic[]} */
export const topics = [
  { id: "ceremony", name: "경조사", color: "rose" },
  { id: "hospital", name: "병원", color: "amber" },
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
    // 항목이 많은 날(달력 자동 접힘 확인용)
    { ...base, id: "b1", kind: "appointment", title: "가족 점심", date: addDays(today, 2), startTime: "12:00", endTime: "14:00", allDay: false, place: "본가" },
    { ...base, id: "b2", kind: "appointment", title: "저녁 영화", date: addDays(today, 2), startTime: "19:00", endTime: "21:00", allDay: false, place: "영화관" },
    { ...base, id: "b3", kind: "todo", title: "케이크 예약하기", date: addDays(today, 2), startTime: "10:00", endTime: "11:00", allDay: false, whoIds: ["dad"] },
    { ...base, id: "b4", kind: "todo", title: "선물 포장하기", date: addDays(today, 2), startTime: "15:00", endTime: "16:00", allDay: false, whoIds: ["dad"] },
    { ...base, id: "b5", kind: "todo", title: "꽃 주문하기", date: addDays(today, 2), startTime: null, endTime: null, allDay: false, whoIds: ["dad"] },
    { ...base, id: "b6", kind: "appointment", title: "아빠 생신 모임", date: addDays(today, 2), startTime: null, endTime: null, allDay: true, whoIds: ["dad"], topicId: "ceremony" },
    // 다음 달 이후(월 구분선)와 더 지난 기록(이전 기록 더 보기) 확인용
    { ...base, id: "f1", kind: "appointment", title: "이모 환갑잔치", date: addDays(today, 20), startTime: "12:00", endTime: "15:00", allDay: false, place: "한정식집", whoIds: ["mom"], topicId: "ceremony" },
    { ...base, id: "f2", kind: "appointment", title: "사촌 돌잔치", date: addDays(today, 60), startTime: "11:30", endTime: "14:00", allDay: false, place: "호텔 연회장", topicId: "ceremony" },
    { ...base, id: "p1", kind: "appointment", title: "치과 진료", date: addDays(today, -8), startTime: "14:00", endTime: "15:00", allDay: false, topicId: "hospital", checked: true },
    { ...base, id: "p2", kind: "todo", title: "공과금 내기", date: addDays(today, -12), startTime: null, endTime: null, allDay: false, checked: true },
    { ...base, id: "p3", kind: "appointment", title: "학부모 상담", date: addDays(today, -20), startTime: "16:00", endTime: "16:30", allDay: false, checked: true },
    { ...base, id: "p4", kind: "appointment", title: "친구 결혼식", date: addDays(today, -35), startTime: "13:00", endTime: "15:00", allDay: false, topicId: "ceremony", checked: true },
  ];
}
