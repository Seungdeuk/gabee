import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

/**
 * 날짜 입력 칸 안의 양력/음력 스위치. 고른 쪽이 갈색 알약으로 채워진다. 누르면 반대쪽으로 바뀐다.
 * @param {{ lunar: boolean, onChange: (lunar: boolean) => void }} props
 */
export default function LunarToggle({ lunar, onChange }) {
  return (
    <Pressable
      onPress={() => onChange(!lunar)}
      accessibilityRole="switch"
      accessibilityState={{ checked: lunar }}
      accessibilityLabel="음력으로 입력"
      hitSlop={6}
      style={styles.track}
    >
      <View style={[styles.thumb, lunar && styles.thumbRight]} />
      <Text style={[styles.label, !lunar && styles.labelOn]}>양력</Text>
      <Text style={[styles.label, lunar && styles.labelOn]}>음력</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  track: {
    width: 84,
    height: 32,
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 16,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  thumb: { position: "absolute", top: 2, left: 2, width: 38, height: 26, borderRadius: 13, backgroundColor: colors.text },
  thumbRight: { left: 40 },
  label: { flex: 1, textAlign: "center", fontSize: 13, color: colors.textMuted },
  labelOn: { color: colors.onDark, fontWeight: "700" },
});
