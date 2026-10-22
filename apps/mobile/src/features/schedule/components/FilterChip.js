import { Pressable, StyleSheet, Text } from "react-native";

import { colors, radius } from "@/theme";

/**
 * 누구·주제 필터 칩. 켜져 있으면 복숭아 바탕 + 굵은 글자. 추가 칩("+ 누구")은 옅은 글자.
 * @param {{ label: string, selected?: boolean, muted?: boolean, onPress?: () => void, onLongPress?: () => void }} props
 */
export default function FilterChip({ label, selected = false, muted = false, onPress, onLongPress }) {
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={[styles.chip, selected && styles.selected]}
    >
      <Text style={[styles.label, muted && styles.muted, selected && styles.labelSelected]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: 11,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  selected: { backgroundColor: colors.peach, borderColor: colors.peach },
  label: { fontSize: 13, fontWeight: "500", color: colors.text },
  muted: { color: colors.textMuted },
  labelSelected: { fontWeight: "700" },
});
