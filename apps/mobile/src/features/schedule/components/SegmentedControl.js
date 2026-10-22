import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

/**
 * 두세 가지 중 하나를 고르는 짧은 선택 막대. 달력|목록, 모두|약속|할 일에 쓴다.
 * @param {{ options: { key: string, label: string }[], value: string, onChange: (key: string) => void, full?: boolean, compact?: boolean }} props
 *   full 이면 가로 가득 채워 같은 너비로 나눈다. compact 이면 좁은 자리용으로 안쪽 여백과 글자를 줄인다.
 */
export default function SegmentedControl({ options, value, onChange, full = false, compact = false }) {
  return (
    <View style={[styles.box, full ? styles.boxFull : styles.boxFit, compact && styles.boxCompact]}>
      {options.map((option) => {
        const on = option.key === value;
        return (
          <Pressable
            key={option.key}
            onPress={() => onChange(option.key)}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            style={[styles.option, full && styles.optionFull, compact && styles.optionCompact, on && styles.optionOn]}
          >
            <Text style={[styles.label, compact && styles.labelCompact, on && styles.labelOn]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flexDirection: "row",
    padding: 3,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  boxFit: { borderRadius: 14, alignSelf: "flex-start" },
  boxFull: { borderRadius: 12 },
  boxCompact: { padding: 2, borderRadius: 12 },
  option: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 11 },
  optionCompact: { paddingHorizontal: 7, paddingVertical: 6, borderRadius: 10 },
  optionFull: { flex: 1, alignItems: "center", paddingHorizontal: 0 },
  optionOn: { backgroundColor: colors.surfaceStrong },
  label: { fontSize: 13, fontWeight: "500", color: colors.textMuted },
  labelCompact: { fontSize: 12 },
  labelOn: { fontWeight: "700", color: colors.text },
});
