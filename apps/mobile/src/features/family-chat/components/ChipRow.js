import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 가로로 넘기는 선택 칩 한 줄(담당자·기한 고르기).
 * @param {{ label: string, options: { key: string, label: string }[], value: string | null, onChange: (key: string) => void }} props label 은 접근성용 이름, value 는 선택된 칩 key(없으면 null)
 */
export default function ChipRow({ label, options, value, onChange }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} keyboardShouldPersistTaps="handled" contentContainerStyle={styles.row} accessibilityLabel={label}>
      {options.map((o) => {
        const selected = o.key === value;
        return (
          <Pressable
            key={o.key}
            onPress={() => onChange(o.key)}
            accessibilityRole="button"
            accessibilityLabel={`${label}: ${o.label}`}
            aria-selected={selected}
            style={[styles.chip, selected && styles.selected]}
          >
            <Text style={[styles.text, selected && styles.selectedText]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: spacing.sm, paddingVertical: spacing.xs },
  chip: { minHeight: 36, justifyContent: "center", paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  selected: { backgroundColor: colors.peach, borderColor: colors.peach },
  text: { ...font.caption, color: colors.textSub },
  selectedText: { color: colors.text, fontFamily: font.bodyStrong.fontFamily },
});
