import { ALL_DAYS, WEEKDAYS } from "./logic";

// 데일리 체크 mock 모음. 습관·기록·응원·온보딩은 서버가 준다. 여기에 남은 것은 두 가지뿐이다.
// 1) 개발용 가상 가족(엄마·아빠·아들·딸·할머니)의 읽기 전용 습관 줄(__DEV__ 에서 실제 가족이 없을 때만 탭에 덧붙는다).
// 2) 개발용 "예시 데이터 채우기"가 서버에 만드는 예시 습관.

/** 개발용 "예시 데이터 채우기"가 서버에 만드는 예시 습관(시안의 내 습관). 완료 기록은 만들지 않는다. */
export const DEV_SAMPLE_ITEMS = [
  { name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: false, shareWithFamily: true },
  { name: "영양제 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true },
  { name: "안부 전화", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: false },
  { name: "알림장 확인", type: "check", goal: 1, unit: "", days: WEEKDAYS, alarm: false, shareWithFamily: true },
];

/** 개발용 가상 가족의 오늘 습관(읽기 전용). id 는 logic.js DEV_FAMILY 와 같다. shareWithFamily 가 꺼진 것도 섞어 두어 빠지는지 볼 수 있다. */
export const FAMILY_ITEMS_MOCK = {
  mom: [
    // note: 서버가 메모를 공개로 준 경우를 흉내 낸다(가족 탭 두 번째 줄 미리보기와 전문 팝업 확인용)
    { id: "m-bp", name: "혈압약 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: true, shareWithFamily: true, note: "혈압약 먹고 괜찮았어요", entry: { done: true, count: 0, doneAt: "08:30" } },
    { id: "m-walk", name: "산책 30분", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "10:12" } },
    { id: "m-water", name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 7, doneAt: null } },
  ],
  dad: [
    { id: "d-vit", name: "영양제 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: true, shareWithFamily: true, note: "식후에 먹었고 속이 편해요", entry: { done: true, count: 0, doneAt: "07:50" } },
    { id: "d-walk", name: "산책 30분", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 0, doneAt: null } },
    { id: "d-water", name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 3, doneAt: null } },
    { id: "d-private", name: "비밀 메모 체크", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: false, entry: { done: false, count: 0, doneAt: null } },
  ],
  // 아들: 알림장 확인·숙제 하기 둘 다 아직 (0/2)
  son: [
    { id: "s-note", name: "알림장 확인", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 0, doneAt: null } },
    { id: "s-hw", name: "숙제 하기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 0, doneAt: null } },
  ],
  // 딸: 숙제 하기 완료, 물 4/8, 스트레칭 완료 (2/5)
  daughter: [
    { id: "g-hw", name: "숙제 하기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "16:40" } },
    { id: "g-water", name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 4, doneAt: null } },
    { id: "g-read", name: "독서 30분", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 0, doneAt: null } },
    { id: "g-stretch", name: "스트레칭", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "19:05" } },
    { id: "g-walk", name: "산책 20분", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 0, doneAt: null } },
  ],
  // 할머니: 혈압 재기 완료 9:05, 약 먹기 미완료, 산책 완료 10:30 (2/3)
  gran: [
    { id: "n-bp", name: "혈압 재기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "09:05" } },
    { id: "n-med", name: "약 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 0, doneAt: null } },
    { id: "n-walk", name: "산책 10분", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "10:30" } },
  ],
};

/** "추천 항목 · 눌러서 바로 추가" 에 나오는 이름. 온보딩 목록에도 쓴다. */
export const RECOMMENDED_NAMES = ["산책하기", "약 먹기", "혈압 재기", "스트레칭", "일기 쓰기"];

/**
 * 새 항목 추가 화면의 "이런 건 어때요?" 추천 후보(시안 AddNew). 목표가 있는 것은 횟수 세기로 채운다.
 * 화면에는 앞에서 세 개만 보이고, 이미 있는 항목 이름은 logic.js recommendAvailable 이 뺀다. 다른 추천으로 넘기지 않는다.
 */
export const RECOMMEND_POOL = [
  { name: "산책하기", goal: 30, unit: "분" },
  { name: "약 먹기" },
  { name: "혈압 재기" },
  { name: "스트레칭", goal: 10, unit: "분" },
  { name: "책 읽기", goal: 10, unit: "쪽" },
  { name: "일기 쓰기" },
  { name: "물 마시기", goal: 8, unit: "잔" },
];
