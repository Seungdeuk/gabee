import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 함께하기 한 줄: 추천 샘플 두 개(↗) + 같이하기 버튼. 터치하면 같이(보내기) 화면으로 간다.
 * @param {{ samples: string[], onPressSample?: (sample: string) => void, onPressTogether?: () => void }} props
 */
export default function TogetherRow({ samples, onPressSample, onPressTogether }) {
  return (
    <View style={styles.row}>
      {samples.map((sample) => (
        <Pressable
          key={sample}
          onPress={() => onPressSample?.(sample)}
          style={[styles.item, styles.sample]}
          accessibilityRole="button"
        >
          <Text style={styles.sampleText} numberOfLines={1}>
            {sample}
          </Text>
          <Text style={styles.arrow}>↗</Text>
        </Pressable>
      ))}
      <Pressable onPress={onPressTogether} style={[styles.item, styles.together]} accessibilityRole="button">
        <Text style={styles.togetherText}>같이하기</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.sm },
  item: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: spacing.md,
    paddingHorizontal: 6,
    borderRadius: radius.button,
  },
  sample: { flex: 1, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  sampleText: { ...font.caption, fontWeight: "500", color: colors.text },
  arrow: { ...font.caption, color: colors.textMuted },
  together: { flex: 0.78, backgroundColor: colors.surfaceStrong },
  togetherText: { fontSize: 14, fontWeight: "700", color: colors.text },
});
