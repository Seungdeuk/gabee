import { Fredoka_600SemiBold } from "@expo-google-fonts/fredoka";
import {
  NotoSansKR_400Regular,
  NotoSansKR_500Medium,
  NotoSansKR_600SemiBold,
  NotoSansKR_700Bold,
  useFonts,
} from "@expo-google-fonts/noto-sans-kr";
import * as NavigationBar from "expo-navigation-bar";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import * as SystemUI from "expo-system-ui";
import { useEffect } from "react";
import { AppState, Platform } from "react-native";

// 백그라운드 위치 작업은 앱이 깨어날 때도 등록돼 있어야 해서 전역에서 불러온다(동의한 사람만 켜진다)
import "@/features/care/location/task";
import { AuthProvider } from "@/shared/auth/AuthProvider";
import { colors } from "@/theme";

// 안드로이드 시스템 내비게이션 바(뒤로·홈)는 숨겨 두고, 화면 아래에서 쓸어 올릴 때만 잠깐 보이게 한다
function useHideNavigationBar() {
  useEffect(() => {
    if (Platform.OS !== "android") return undefined;
    // 바를 숨겨 비는 자리가 흰색으로 남지 않도록 창 바탕색을 앱 색으로 맞춘다
    SystemUI.setBackgroundColorAsync(colors.background).catch(() => {});
    const hide = () => NavigationBar.setVisibilityAsync("hidden").catch(() => {});
    hide();
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") hide();
    });
    return () => sub.remove();
  }, []);
}

export default function RootLayout() {
  useHideNavigationBar();
  // 로고 글꼴(Fredoka)과 본문 글꼴(Noto Sans KR). 불러오지 못해도 앱은 기본 글꼴로 계속 쓸 수 있다.
  const [loaded, error] = useFonts({
    Fredoka_600SemiBold,
    NotoSansKR_400Regular,
    NotoSansKR_500Medium,
    NotoSansKR_600SemiBold,
    NotoSansKR_700Bold,
  });
  if (!loaded && !error) return null;

  return (
    <>
      <StatusBar style="dark" />
      <AuthProvider>
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }} />
      </AuthProvider>
    </>
  );
}
