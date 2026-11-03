// 저장할 표가 아직 없는 메뉴(AI 이용·피드백·문의)의 예시 데이터. 2단계에서 서버 API 로 바뀐다.
// 실제 사용자 정보가 아니다.
window.ADMIN_MOCK = {
  ai: {
    today: 320,
    week: 1980,
    month: 4520,
    daily: [120, 140, 110, 160, 180, 150, 130, 170, 210, 190, 230, 260, 300, 320],
    rows: [
      { name: "AI 비서 채팅", calls: 2140 },
      { name: "정산 에이전트", calls: 880 },
      { name: "일정 에이전트", calls: 760 },
      { name: "가족 채팅 도우미", calls: 510 },
      { name: "사진 분석", calls: 312 },
      { name: "돌봄 에이전트", calls: 230 },
    ],
  },

  feedback: {
    rows: [
      { kind: "불편 사항", feature: "소통", text: "사진을 여러 장 보내면 순서가 바뀌어요", date: "11-02", status: "new" },
      { kind: "개선 요청", feature: "일정", text: "반복 일정을 격주로도 만들고 싶어요", date: "11-01", status: "new" },
      { kind: "의견", feature: "AI 채팅", text: "가비 답이 친절해서 좋아요", date: "10-31", status: "seen" },
      { kind: "불편 사항", feature: "정산", text: "용돈 금액에 쉼표가 안 들어가요", date: "10-30", status: "planned" },
      { kind: "개선 요청", feature: "돌봄", text: "약 먹을 시간 알림이 있으면 좋겠어요", date: "10-29", status: "done" },
    ],
  },

  support: {
    rows: [
      { no: 1042, kind: "문의", title: "비밀번호를 바꾸고 싶어요", date: "11-02", status: "new" },
      { no: 1041, kind: "신고", title: "가족 채팅방에 모르는 사람이 있어요", date: "11-01", status: "new" },
      { no: 1040, kind: "문의", title: "가족 그룹에서 나가는 방법", date: "10-31", status: "working" },
      { no: 1039, kind: "문의", title: "탈퇴하면 사진도 지워지나요?", date: "10-30", status: "done" },
      { no: 1038, kind: "신고", title: "광고 메시지를 받았어요", date: "10-29", status: "done" },
    ],
  },
};
