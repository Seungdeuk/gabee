import { Fredoka_600SemiBold, useFonts } from "@expo-google-fonts/fredoka";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import { colors } from "@/theme";

export default function RootLayout() {
  // 로고 글꼴(Fredoka). 불러오지 못해도 앱은 기본 글꼴로 계속 쓸 수 있다.
  const [loaded, error] = useFonts({ Fredoka_600SemiBold });
  if (!loaded && !error) return null;

  return (
    <>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }} />
    </>
  );
}
