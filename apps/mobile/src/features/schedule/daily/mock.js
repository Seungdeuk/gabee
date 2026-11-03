import { ALL_DAYS, WEEKDAYS, shiftDayKey } from "./logic";

// 데일리 체크 화면 확인용 임시 데이터. 가족 기록·전화번호·받은 응원은 서버가 없어 여기서 주고, 서버 연결 때 api.js 의 함수만 바꾼다.
// 각 항목의 entry 는 "오늘" 기록이다(done, count, doneAt "HH:MM").

/**
 * 개발용 "예시 데이터 채우기"(편집 화면, __DEV__ 에서만 보임)가 넣는 내 항목(시안 Main.dc.html 의 데이터).
 * 처음 열 때 자동으로 들어가지 않는다(온보딩으로 시작한다).
 */
export const SEED_ITEMS = [
  { id: "seed-water", name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: false, shareWithFamily: true },
  { id: "seed-vit", name: "영양제 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true },
  { id: "seed-call", name: "부모님께 안부 전화", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: false },
  { id: "seed-note", name: "알림장 확인", type: "check", goal: 1, unit: "", days: WEEKDAYS, alarm: false, shareWithFamily: true },
];

/** 시드 항목의 오늘 기록: 물 5/8, 영양제 8:10 완료, 알림장 4:30 완료(오후), 안부 전화는 미완료. */
export const SEED_ENTRIES = {
  "seed-water": { done: false, count: 5, doneAt: null },
  "seed-vit": { done: true, count: 0, doneAt: "08:10" },
  "seed-note": { done: true, count: 0, doneAt: "16:30" },
};

/** 가족 구성원 id → 그 사람의 항목(가족에게 보이기 꺼진 것도 섞어 두어 가족 탭에서 빠지는지 볼 수 있다). */
export const FAMILY_ITEMS_MOCK = {
  mom: [
    { id: "m-bp", name: "혈압약 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: true, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "08:30" } },
    { id: "m-walk", name: "산책 30분", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "10:12" } },
    { id: "m-water", name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, alarm: false, shareWithFamily: true, entry: { done: false, count: 7, doneAt: null } },
  ],
  dad: [
    { id: "d-vit", name: "영양제 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, alarm: true, shareWithFamily: true, entry: { done: true, count: 0, doneAt: "07:50" } },
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

/** 가족 구성원 전화 mock. masked 는 화면에 보이는 가린 번호, dial 은 전화 앱에 넘기는 번호다(끝 4자리가 같다). */
export const FAMILY_PHONE_MOCK = {
  mom: { masked: "010-****-1234", dial: "01011111234" },
  dad: { masked: "010-****-5678", dial: "01022225678" },
  son: { masked: "010-****-3333", dial: "01044443333" },
  daughter: { masked: "010-****-6666", dial: "01055556666" },
  gran: { masked: "010-****-9999", dial: "01066669999" },
};

/**
 * 개발용 예시 받은 응원(시안 CheerReceived 와 CheerHistory 의 내용). 날짜는 오늘 기준으로 만든다.
 * @returns {object[]} 응원 기록 { id, direction: "received", fromName, kind, text, date, time, thanked, groupChat }
 */
export function seedCheers(today) {
  const yesterday = shiftDayKey(today, -1);
  const threeDaysAgo = shiftDayKey(today, -3);
  return [
    { id: "seed-cheer-1", direction: "received", fromName: "아들", kind: "love", text: "오늘도 다 챙기셨네요, 최고예요", date: today, time: "16:02", thanked: false, groupChat: false },
    { id: "seed-cheer-2", direction: "received", fromName: "딸", kind: "well", text: "오늘도 고생 많으셨어요", date: today, time: "15:50", thanked: false, groupChat: false },
    { id: "seed-cheer-3", direction: "received", fromName: "딸", kind: "best", text: "물 한 잔만 더 드시면 돼요", date: yesterday, time: "20:15", thanked: false, groupChat: false },
    { id: "seed-cheer-4", direction: "received", fromName: "아빠", kind: "well", text: "오늘도 고생 많으셨어요", date: threeDaysAgo, time: "11:40", thanked: true, groupChat: false },
  ];
}

/** "추천 항목 · 눌러서 바로 추가" 에 나오는 이름. 누르면 한 번 체크, 매일, 가족에게 보이기로 추가된다. 온보딩 목록에도 쓴다. */
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
