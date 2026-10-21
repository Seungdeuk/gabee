// 가비 AI 채팅 디자인(원본: 에이닷) 기준 디자인 토큰. 따뜻한 크림 바탕에 브라운 글자, 꿀벌 색 포인트.
export const colors = {
  // 글자
  text: "#553B29",
  textSub: "#6B5444",
  textMuted: "#7A6352",
  placeholder: "#A89484",
  disabled: "#CBBBAE",

  // 바탕과 면
  background: "#FFFCF7",
  card: "#FFFFFF",
  surface: "#FEF3DA", // 입력창, 옅은 카드
  surfaceStrong: "#FEECBF", // 선택된 탭 알약, 태그
  border: "#F0E2CF", // 카드 테두리
  divider: "#EFE6DA", // 목록 구분선

  // 포인트
  accent: "#B7791C", // 로고의 "Bee", 강조 글자
  primary: "#B7791C",
  primaryDark: "#553B29",
  primarySoft: "#FEECBF",
  peach: "#FEB49A", // 내 말풍선, 큰 버튼, 읽지 않음 표시
  peachSoft: "#FFEDE5",
  honeySoft: "#FEF0CC",
  dark: "#553B29", // 가장 중요한 버튼
  onDark: "#FFFFFF",

  // 상태
  success: "#456C57",
  successSoft: "#E4F0E8",
  warning: "#B7791C",
  warningSoft: "#FEECBF",
  danger: "#C2503A",
  dangerSoft: "#FFEDE5",
  purple: "#8A5A44",
  purpleSoft: "#FFEDE5",
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
};

export const radius = {
  sm: 10,
  md: 12,
  button: 16,
  lg: 16,
  card: 20,
  bubble: 18,
  pill: 999,
};

// 로고(Ga + Bee)에 쓰는 글꼴 이름. 앱을 시작할 때 app/_layout.js 에서 불러온다.
export const fonts = {
  logo: "Fredoka_600SemiBold",
};

export const font = {
  h1: { fontSize: 24, lineHeight: 34, fontWeight: "700" },
  page: { fontSize: 26, fontWeight: "700" },
  title: { fontSize: 20, fontWeight: "700" },
  section: { fontSize: 17, fontWeight: "700" },
  cardTitle: { fontSize: 16, fontWeight: "700" },
  body: { fontSize: 15, lineHeight: 24 },
  bodyStrong: { fontSize: 15, fontWeight: "600" },
  caption: { fontSize: 13, lineHeight: 20 },
  tab: { fontSize: 11 },
};
