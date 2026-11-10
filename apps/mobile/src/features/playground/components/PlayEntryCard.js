import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius } from "@/theme";

import { TODO } from "../mock";

/** 소통 탭 "가족 연락처" 아래의 가족 놀이터 입구 카드. */
export default function PlayEntryCard() {
  const router = useRouter();
  return (
    <Pressable onPress={() => router.push("/play")} accessibilityRole="button" accessibilityLabel={`가족 놀이터. 내 차례인 게임 ${TODO.length}개가 기다려요`} style={styles.card}>
      <View style={styles.icon}>
        <Ionicons name="game-controller-outline" size={22} color={colors.text} />
      </View>
      <View style={styles.text}>
        <Text style={styles.title}>가족 놀이터</Text>
        <Text style={styles.sub}>내 차례인 게임 {TODO.length}개가 기다려요</Text>
      </View>
      <Ionicons name="chevron-forward" size={20} color={colors.textSub} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 11, paddingHorizontal: 13, borderRadius: radius.lg, backgroundColor: colors.surfaceStrong },
  icon: { width: 38, height: 38, borderRadius: 11, backgroundColor: colors.background, alignItems: "center", justifyContent: "center" },
  text: { flex: 1 },
  title: { ...font.cardTitle, fontSize: 15, lineHeight: 20, color: colors.text },
  sub: { ...font.caption, fontSize: 12, lineHeight: 16, color: colors.textSub },
});
