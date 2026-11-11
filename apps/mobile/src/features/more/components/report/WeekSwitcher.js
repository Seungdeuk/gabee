import { Pressable, StyleSheet, Text, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 주 이동 줄: ‹ [제목 / 날짜 범위] ›. 지난 주를 보고 있으면 아래에 "이번 주로" 칩이 나온다.
 * @param {{ range: { title: string, label: string, offset: number }, canPrev: boolean, canNext: boolean, onPrev: () => void, onNext: () => void, onCurrent: () => void }} props
 * @returns {import("react").ReactElement}
 */
export default function WeekSwitcher({ range, canPrev, canNext, onPrev, onNext, onCurrent }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <IconButton name="chevron-back" label="이전 주" onPress={onPrev} disabled={!canPrev} />
        <View style={styles.center} accessibilityRole="header" accessibilityLabel={`${range.title}, ${range.label}`}>
          <Text style={styles.title}>{range.title}</Text>
          <Text style={styles.label}>{range.label}</Text>
        </View>
        <IconButton name="chevron-forward" label="다음 주" onPress={onNext} disabled={!canNext} />
      </View>
      {range.offset < 0 ? (
        <Pressable style={styles.chip} onPress={onCurrent} accessibilityRole="button" accessibilityLabel="이번 주로">
          <Text style={styles.chipText}>이번 주로</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", gap: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", alignSelf: "stretch" },
  center: { alignItems: "center", gap: spacing.xs },
  title: { ...font.cardTitle, color: colors.text },
  label: { ...font.caption, color: colors.textMuted },
  chip: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceStrong,
  },
  chipText: { ...font.caption, color: colors.text },
});
