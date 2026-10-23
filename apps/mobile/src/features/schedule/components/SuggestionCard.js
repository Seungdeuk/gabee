import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

/**
 * "먼저 권해드려요" 카드 한 장. 문장(+ 선택으로 둘째 줄) 아래 줄 오른쪽에 작은 버튼 두 개와 새로고침. 버튼은 처음엔 둘 다 흰색이고, 고른 쪽이 복숭아색으로 바뀐다. 버튼이 없으면 문장만 보인다.
 * @param {{ text: string, subtext?: string, primary?: string, secondary?: string, onPrimary?: () => void, onSecondary?: () => void, primarySelected?: boolean, secondarySelected?: boolean, primaryDisabled?: boolean, onRefresh?: () => void }} props
 *   onRefresh 가 있으면 버튼 오른쪽에 이 카드만 바꾸는 새로고침 아이콘이 보인다(질문이 있는 카드에는 항상 둔다).
 */
export default function SuggestionCard({
  text,
  subtext,
  primary,
  secondary,
  onPrimary,
  onSecondary,
  primarySelected = false,
  secondarySelected = false,
  primaryDisabled = false,
  onRefresh,
}) {
  return (
    <View style={styles.card}>
      <View style={styles.texts}>
        <Text style={styles.text}>{text}</Text>
        {subtext ? <Text style={styles.subtext}>{subtext}</Text> : null}
      </View>
      {primary || secondary || onRefresh ? (
        <View style={styles.actions}>
          {primary ? (
            <Pressable
              onPress={onPrimary}
              disabled={primaryDisabled}
              style={[styles.button, primarySelected && styles.selected]}
              accessibilityRole="button"
              accessibilityState={{ selected: primarySelected, disabled: primaryDisabled }}
            >
              <Text style={[styles.label, primarySelected && styles.labelSelected]}>{primary}</Text>
            </Pressable>
          ) : null}
          {secondary ? (
            <Pressable
              onPress={onSecondary}
              style={[styles.button, secondarySelected && styles.selected]}
              accessibilityRole="button"
              accessibilityState={{ selected: secondarySelected }}
            >
              <Text style={[styles.label, secondarySelected && styles.labelSelected]}>{secondary}</Text>
            </Pressable>
          ) : null}
          {onRefresh ? (
            <Pressable onPress={onRefresh} style={styles.refresh} accessibilityRole="button" accessibilityLabel="다른 것 보기">
              <Ionicons name="refresh" size={18} color={colors.text} />
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: spacing.sm,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
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
  texts: { paddingRight: spacing.sm },
  text: { fontSize: 16, lineHeight: 22, fontWeight: "500", color: colors.text },
  subtext: { fontSize: 16, lineHeight: 22, color: colors.textMuted },
  actions: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", gap: 6 },
  button: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  refresh: { width: 34, height: 34, alignItems: "center", justifyContent: "center", borderRadius: radius.md },
  selected: { backgroundColor: colors.peach, borderColor: colors.peach },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  labelSelected: { fontWeight: "700" },
});
