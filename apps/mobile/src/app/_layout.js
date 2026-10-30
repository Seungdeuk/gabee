import { Fredoka_600SemiBold } from "@expo-google-fonts/fredoka";
import {
  NotoSansKR_400Regular,
  NotoSansKR_500Medium,
  NotoSansKR_600SemiBold,
  NotoSansKR_700Bold,
  useFonts,
} from "@expo-google-fonts/noto-sans-kr";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { StyleSheet } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";

// 백그라운드 위치 작업은 앱이 깨어날 때도 등록돼 있어야 해서 전역에서 불러온다(동의한 사람만 켜진다)
import "@/features/care/location/task";
import { AuthProvider } from "@/shared/auth/AuthProvider";
import { colors } from "@/theme";

export default function RootLayout() {
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
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }} />
      </AuthProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
