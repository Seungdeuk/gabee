import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { reactionLabel } from "../messageActions";

/**
 * 말풍선 아래 반응 칩 줄: 이모지와 사람 수. 내가 누른 칩은 꿀색으로 강조하고, 누르면 내 반응을 켜거나(남이 누른 이모지) 취소한다(내가 누른 이모지).
 * 반응이 없으면 아무것도 그리지 않는다.
 * @param {{ reactions: { emoji: string, count: number, mine: boolean }[] | undefined, onPress?: (emoji: string) => void, align?: "start" | "end" }} props
 */
export default function ReactionRow({ reactions, onPress, align = "start" }) {
  if (!reactions?.length) return null;
  return (
    <View style={[styles.row, align === "end" && styles.end]}>
      {reactions.map((r) => (
        <Pressable
          key={r.emoji}
          onPress={onPress ? () => onPress(r.emoji) : undefined}
          disabled={!onPress}
          accessibilityRole="button"
          accessibilityLabel={reactionLabel(r)}
          accessibilityState={{ selected: r.mine }}
          style={[styles.chip, r.mine && styles.mine]}
        >
          <Text style={styles.emoji}>{r.emoji}</Text>
          <Text style={[styles.count, r.mine && styles.countMine]}>{r.count}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.xs },
  end: { justifyContent: "flex-end" },
  chip: { minHeight: spacing.lg + spacing.xs, flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.xs + spacing.xs / 2, borderRadius: radius.pill, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  mine: { backgroundColor: colors.honeySoft, borderColor: colors.accent },
  emoji: { fontSize: Math.round(font.tab.fontSize * 0.6), lineHeight: font.tab.fontSize + spacing.xs }, // 이모지는 작은 글자(tab)의 60% 크기(칩이 말풍선보다 눈에 띄지 않게)
  count: { ...font.tab, color: colors.textMuted },
  countMine: { color: colors.text, fontFamily: font.bodyStrong.fontFamily },
});
