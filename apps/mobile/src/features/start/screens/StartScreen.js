import { Image } from "expo-image";
import { Redirect, useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/shared/auth/AuthProvider";
import Logo from "@/shared/components/Logo";
import { colors } from "@/theme";

import mascot from "../../../../assets/images/gabee-mascot.png";

/**
 * 시작 화면. 큰 원 안에 가비(꿀벌)가 있고, 시작하기로 AI 채팅 홈에 들어간다.
 * 로그인 세션이 저장돼 있으면 이 화면을 건너뛰고 홈으로 간다. "시작하기"는 기존처럼 로그인 없이 들어가고(익명/개발용 토큰),
 * 정식 회원은 로그인·회원가입으로 들어간다.
 */
export default function StartScreen() {
  const router = useRouter();
  const { status } = useAuth();
  const enter = () => router.replace("/chat");

  if (status === "loading") return null; // 저장된 로그인 세션을 확인하는 동안(스플래시 직후 잠깐)
  if (status === "authenticated") return <Redirect href="/chat" />;

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.hero}>
        <View style={styles.halo} />
        <View style={styles.badge}>
          <Image source={mascot} style={styles.mascot} contentFit="contain" accessibilityLabel="가비" />
        </View>
      </View>

      <View style={styles.copy}>
        <Logo size={30} />
        <Text style={styles.title}>당신 곁의{"\n"}가족 생활 비서</Text>
        <Text style={styles.sub}>사진 한 장으로{"\n"}가족 모두의 이야기를 만들어가요</Text>
      </View>

      <View style={styles.footer}>
        <Pressable onPress={enter} style={styles.button} accessibilityRole="button">
          <Text style={styles.buttonText}>시작하기</Text>
        </Pressable>
        <Text style={styles.login}>
          이미 계정이 있나요?{" "}
          <Text style={styles.loginLink} onPress={() => router.push("/login")} accessibilityRole="link">
            로그인
          </Text>
          {"  ·  "}
          <Text style={styles.loginLink} onPress={() => router.push("/signup")} accessibilityRole="link">
            회원가입
          </Text>
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  hero: { height: 340, alignItems: "center", justifyContent: "center" },
  halo: {
    position: "absolute",
    width: 280,
    height: 280,
    borderRadius: 140,
    backgroundColor: colors.surface,
  },
  badge: {
    width: 196,
    height: 196,
    borderRadius: 98,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: colors.text,
    shadowOpacity: 0.14,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 10 },
    elevation: 6,
  },
  mascot: { width: 168, height: 102, marginLeft: 4 },
  copy: { flex: 1, alignItems: "center", paddingHorizontal: 24, paddingTop: 8 },
  title: {
    marginTop: 14,
    fontSize: 28,
    lineHeight: 38,
    fontWeight: "700",
    color: colors.text,
    textAlign: "center",
  },
  sub: {
    marginTop: 14,
    fontSize: 15,
    lineHeight: 24,
    color: colors.textSub,
    textAlign: "center",
  },
  footer: { paddingHorizontal: 24, paddingBottom: 28, alignItems: "center", gap: 16 },
  button: {
    width: "100%",
    height: 56,
    borderRadius: 16,
    backgroundColor: colors.peach,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: { fontSize: 17, fontWeight: "700", color: colors.text },
  login: { fontSize: 14, color: colors.textMuted },
  loginLink: { fontWeight: "700", color: colors.text },
});
