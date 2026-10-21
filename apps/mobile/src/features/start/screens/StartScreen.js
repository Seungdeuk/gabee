import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Logo from "@/shared/components/Logo";
import { colors } from "@/theme";

import mascot from "../../../../assets/images/gabee-mascot.png";

/**
 * 시작 화면. 큰 원 안에 가비(꿀벌)가 있고, 시작하기로 AI 채팅 홈에 들어간다.
 * TODO: 이미 가입한 사람은(저장된 토큰이 있으면) 이 화면을 건너뛰고, "로그인"은 가족 그룹 로그인으로 연결한다.
 */
export default function StartScreen() {
  const router = useRouter();
  const enter = () => router.replace("/chat");

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
        <Text style={styles.sub}>영수증·고지서·처방전을 찍으면{"\n"}가족이 함께 보는 기록이 돼요</Text>
      </View>

      <View style={styles.footer}>
        <Pressable onPress={enter} style={styles.button} accessibilityRole="button">
          <Text style={styles.buttonText}>시작하기</Text>
        </Pressable>
        <Text style={styles.login}>
          이미 가족 그룹이 있나요?{" "}
          <Text style={styles.loginLink} onPress={enter} accessibilityRole="link">
            로그인
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
