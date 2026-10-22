import { Stack } from "expo-router";

import { colors } from "@/theme";

// 일정 탭 안의 화면(메인, 달력, ...)을 쌓는 스택. 하단 탭 바는 바깥 (tabs) 레이아웃이 그대로 보여 준다.
export default function ScheduleLayout() {
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }} />;
}
