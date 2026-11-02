import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import { shiftMonth } from "../format";

/**
 * 월 이동 막대(이전 달 ‹ 2026-10 › 다음 달).
 * @param {{ month: string, onChange: (month: string) => void }} props month: "YYYY-MM"
 */
export default function MonthSwitcher({ month, onChange }) {
  return (
    <View style={styles.row}>
      <Pressable onPress={() => onChange(shiftMonth(month, -1))} accessibilityRole="button" accessibilityLabel="이전 달" style={styles.arrow}>
        <Ionicons name="chevron-back" size={22} color={colors.text} />
      </Pressable>
      <Text style={styles.month} testID="month-label">
        {month}
      </Text>
      <Pressable onPress={() => onChange(shiftMonth(month, 1))} accessibilityRole="button" accessibilityLabel="다음 달" style={styles.arrow}>
        <Ionicons name="chevron-forward" size={22} color={colors.text} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 16 },
  arrow: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  month: { ...font.title, color: colors.text, minWidth: 96, textAlign: "center" },
});
