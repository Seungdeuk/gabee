import { StyleSheet, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

/**
 * 불러오는 동안 보여 주는 뼈대: 말풍선, 숫자 띠, 목록 3행.
 * @returns {import("react").ReactElement}
 */
export default function ReportSkeleton() {
  return (
    <View style={styles.wrap} accessibilityLabel="리포트를 불러오는 중이에요" accessibilityRole="progressbar">
      <View style={styles.bubbleRow}>
        <View style={styles.mascot} />
        <View style={styles.bubble} />
      </View>
      <View style={styles.band} />
      <View style={styles.list}>
        {[0, 1, 2].map((i) => (
          <View key={i} style={styles.row} />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xl },
  bubbleRow: { flexDirection: "row", gap: spacing.md },
  mascot: { width: 56, height: 56, borderRadius: radius.lg, backgroundColor: colors.surface },
  bubble: { flex: 1, height: 80, borderRadius: radius.bubble, backgroundColor: colors.surface },
  band: { height: 96, borderRadius: radius.card, backgroundColor: colors.surface },
  list: { gap: spacing.sm },
  row: { height: 56, borderRadius: radius.md, backgroundColor: colors.surface },
});
