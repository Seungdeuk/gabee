import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

/**
 * "먼저 권해드려요" 카드 한 장. 문장 + 오른쪽 작은 버튼 두 개(채움 / 테두리). 버튼이 없으면 문장만 보인다.
 * @param {{ text: string, primary?: string, secondary?: string, onPrimary?: () => void, onSecondary?: () => void }} props
 */
export default function SuggestionCard({ text, primary, secondary, onPrimary, onSecondary }) {
  return (
    <View style={styles.card}>
      <Text style={styles.text}>{text}</Text>
      {primary || secondary ? (
        <View style={styles.actions}>
          {primary ? (
            <Pressable onPress={onPrimary} style={[styles.button, styles.primary]} accessibilityRole="button">
              <Text style={styles.primaryText}>{primary}</Text>
            </Pressable>
          ) : null}
          {secondary ? (
            <Pressable onPress={onSecondary} style={[styles.button, styles.ghost]} accessibilityRole="button">
              <Text style={styles.ghostText}>{secondary}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 10,
    paddingVertical: spacing.sm,
    paddingLeft: spacing.lg,
    paddingRight: spacing.sm,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
    shadowColor: colors.text,
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  text: { flexGrow: 1, flexShrink: 1, flexBasis: 140, fontSize: 16, lineHeight: 22, color: colors.text },
  actions: { flexDirection: "row", gap: 6 },
  button: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.md },
  primary: { backgroundColor: colors.peach },
  primaryText: { fontSize: 14, fontWeight: "700", color: colors.text },
  ghost: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  ghostText: { fontSize: 14, fontWeight: "500", color: colors.text },
});
