import { Pressable, StyleSheet, Text } from "react-native";

import { colors, font, radius } from "@/theme";

/**
 * 누구·주제 필터나 선택 칩. 켜져 있으면 진한 바탕.
 * @param {{ label: string, selected?: boolean, onPress?: () => void, onLongPress?: () => void }} props
 */
export default function FilterChip({ label, selected = false, onPress, onLongPress }) {
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={[styles.chip, selected && styles.selected]}
    >
      <Text style={[styles.label, selected && styles.labelSelected]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    minHeight: 36,
    paddingHorizontal: 14,
    justifyContent: "center",
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
  },
  selected: { backgroundColor: colors.dark },
  label: { ...font.bodyStrong, color: colors.textSub },
  labelSelected: { color: colors.onDark },
});
