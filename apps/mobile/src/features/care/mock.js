// 화면 확인용 임시 데이터. 서버 연동 시 api.js로 교체한다.
export const today = {
  date: "10월 12일 월요일",
  person: "영희님",
  quote: "오늘은 보통이야. 아침 먹었어.",
  source: "전화로 확인 · 지민이 기록 · 09:10",
};

export const checks = [
  { id: "1", title: "컨디션", note: "09:10 · 지민", status: "보통이에요", tone: "green", icon: "happy" },
  { id: "2", title: "식사", note: "09:10 · 지민", status: "아침 드셨어요", tone: "green", icon: "restaurant" },
  { id: "3", title: "약 복용", note: "10.11 저녁", status: "가족 확인 필요", tone: "orange", icon: "medkit" },
  { id: "4", title: "걷기", note: "최근 10.10 20분", status: "오늘 미기록", tone: "gray", icon: "walk" },
];
