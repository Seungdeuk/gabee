import { colors } from "@/theme";

// 항목 형태. 약속 = 그날 그 시간에 일어나는 것, 할 일 = 체크하면 끝나는 것.
export const KIND = { appointment: "appointment", todo: "todo" };

export const KIND_LABEL = {
  [KIND.appointment]: "약속",
  [KIND.todo]: "할 일",
};

// 체크의 뜻이 형태마다 다르다 (약속 = 확인, 할 일 = 완료).
export const CHECK_LABEL = {
  [KIND.appointment]: "확인했어요",
  [KIND.todo]: "완료했어요",
};

// 카드 왼쪽 막대 색. UI Kit 에 정의가 없어 임시로 파생한 값이라 디자인 확인 후 theme 으로 옮긴다.
export const KIND_COLOR = {
  [KIND.appointment]: colors.peach,
  [KIND.todo]: colors.success,
};

// 주제 색. 이것도 UI Kit 미정의 임시 값.
export const TOPIC_COLORS = {
  honey: { bg: colors.honeySoft, fg: colors.accent },
  peach: { bg: colors.peachSoft, fg: colors.danger },
  green: { bg: colors.successSoft, fg: colors.success },
  brown: { bg: colors.surfaceStrong, fg: colors.text },
};

export const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
