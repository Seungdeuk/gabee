// 화면 확인용 임시 데이터. 서버 연동 시 각 기능의 api.js 로 교체한다.
export const today = {
  date: "10월 12일 월요일",
  family: "우리 가족 · 4명 연결",
  checks: [
    { id: "1", title: "컨디션", status: "보통이에요", tone: "green", icon: "happy" },
    { id: "2", title: "식사", status: "아침 드셨어요", tone: "green", icon: "restaurant" },
    { id: "3", title: "약 복용", status: "가족 확인 필요", tone: "orange", icon: "medkit" },
    { id: "4", title: "걷기", status: "오늘 미기록", tone: "gray", icon: "walk" },
  ],
  notice: "10.11 저녁 약 복용 여부 미확인. 미확인은 미복용을 뜻하지 않아요.",
};

export const group = {
  name: "우리 가족",
  inviteCode: "GY2612AB",
  members: [
    { id: "1", name: "지민", role: "관리자 · 나" },
    { id: "2", name: "영희", role: "어머니" },
    { id: "3", name: "정호", role: "아버지" },
    { id: "4", name: "수진", role: "가족" },
  ],
};
