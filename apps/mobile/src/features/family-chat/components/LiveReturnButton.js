import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, Pressable, StyleSheet, Text } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 과거 대화를 보는 동안 화면 아래에 떠 있는 "최신 대화로 이동" 버튼. 누르면 라이브(최근 대화 + 새 메시지 확인)로 돌아간다.
 * @param {{ onPress: () => void, busy?: boolean }} props
 */
export default function LiveReturnButton({ onPress, busy = false }) {
  return (
    <Pressable onPress={onPress} disabled={busy} accessibilityRole="button" accessibilityLabel="최신 대화로 이동" accessibilityState={{ busy, disabled: busy }} style={styles.pill}>
      {busy ? <ActivityIndicator size="small" color={colors.text} /> : <Ionicons name="arrow-down" size={16} color={colors.text} />}
      <Text style={styles.text}>최신 대화로 이동</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pill: {
    position: "absolute",
    alignSelf: "center",
    bottom: spacing.lg,
    minHeight: 40,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.peach,
    borderWidth: 1,
    borderColor: colors.border,
  },
  text: { ...font.bodyStrong, color: colors.text },
});
