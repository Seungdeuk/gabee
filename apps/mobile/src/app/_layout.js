import { Fredoka_600SemiBold } from "@expo-google-fonts/fredoka";
import {
  NotoSansKR_400Regular,
  NotoSansKR_500Medium,
  NotoSansKR_600SemiBold,
  NotoSansKR_700Bold,
  useFonts,
} from "@expo-google-fonts/noto-sans-kr";
import { useKeepAwake } from "expo-keep-awake";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { StyleSheet } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";

// 백그라운드 위치 작업은 앱이 깨어날 때도 등록돼 있어야 해서 전역에서 불러온다(동의한 사람만 켜진다)
import AcquisitionBootstrap from "@/features/acquisition/AcquisitionBootstrap";
import PushBootstrap from "@/features/notifications/PushBootstrap";
import UsageTracker from "@/features/usage/UsageTracker";
import { AuthProvider } from "@/shared/auth/AuthProvider";
import { registerSignOutImageCacheClear } from "@/shared/imageCache";
import { startMeta } from "@/shared/meta/metaEvents";
import { colors } from "@/theme";

export default function RootLayout() {
  // 앱을 쓰는 동안 터치가 없어도 화면이 꺼지지 않게 한다(사용자 요청: 앱 전체). 아래 조기 반환보다 먼저 불러야 한다
  useKeepAwake();
  // 로그아웃 직전에 이미지 캐시(메모리·디스크)를 비운다: 같은 기기에서 다른 사람이 로그인해도 이전 사용자의 인증 사진이 남지 않게 한다
  useEffect(() => registerSignOutImageCacheClear(), []);
  // 메타 광고 측정(설치·실행 기록). Expo Go·웹에서는 아무것도 하지 않는다
  useEffect(() => startMeta(), []);
  // 로고 글꼴(Fredoka)과 본문 글꼴(Noto Sans KR). 불러오지 못해도 앱은 기본 글꼴로 계속 쓸 수 있다.
  const [loaded, error] = useFonts({
    Fredoka_600SemiBold,
    NotoSansKR_400Regular,
    NotoSansKR_500Medium,
    NotoSansKR_600SemiBold,
    NotoSansKR_700Bold,
  });
  if (!loaded && !error) return null;

  // 소통 탭 방 행의 스와이프(알림 끄기)가 제스처를 받으려면 앱 전체를 GestureHandlerRootView 로 감싸야 한다
  return (
    <GestureHandlerRootView style={styles.root}>
      <StatusBar style="dark" />
      <AuthProvider>
        <PushBootstrap />
        {/* 플레이 스토어 설치 꼬리표(유입 경로)를 로그인 뒤 한 번 서버에 보낸다(안드로이드만) */}
        <AcquisitionBootstrap />
        {/* 앱이 화면에 떠 있던 시간을 탭별로 모아 뒤로 갈 때 한 번 보낸다(체류시간) */}
        <UsageTracker />
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }} />
      </AuthProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
