import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

/**
 * 화면 안에서 구역을 바꾸는 알약형 선택 막대.
 * @param {{ options: { key: string, label: string }[], value: string, onChange: (key: string) => void }} props
 */
export default function Segmented({ options, value, onChange }) {
  return (
    <View style={styles.bar} accessibilityRole="tablist">
      {options.map((o) => {
        const active = o.key === value;
        return (
          <Pressable
            key={o.key}
            onPress={() => onChange(o.key)}
            accessibilityRole="tab"
            aria-selected={active}
            style={[styles.item, active && styles.itemActive]}
          >
            <Text style={[styles.label, active && styles.labelActive]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: "row", backgroundColor: colors.surface, borderRadius: 14, padding: 4 },
  item: { flex: 1, height: 40, borderRadius: 11, alignItems: "center", justifyContent: "center" },
  itemActive: { backgroundColor: colors.card },
  label: { fontSize: 13, fontWeight: "500", color: colors.textMuted },
  labelActive: { fontWeight: "700", color: colors.text },
});
