import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import { WEEKDAYS } from "../constants";
import { fromDateKey, todayKey, weekOf } from "../utils/date";

/**
 * 한 주(일~토) 날짜 줄. 오늘은 진하게, 선택한 날짜는 알약 바탕.
 * @param {{ selected: string, onSelect: (dateKey: string) => void }} props
 */
export default function WeekStrip({ selected, onSelect }) {
  const today = todayKey();
  return (
    <View style={styles.row}>
      {weekOf(selected).map((key) => {
        const d = fromDateKey(key);
        const isSelected = key === selected;
        return (
          <Pressable key={key} onPress={() => onSelect(key)} style={styles.cell} accessibilityRole="button">
            <Text style={styles.weekday}>{WEEKDAYS[d.getDay()]}</Text>
            <View style={[styles.day, isSelected && styles.daySelected]}>
              <Text style={[styles.dayText, key === today && styles.today]}>{d.getDate()}</Text>
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", justifyContent: "space-between" },
  cell: { flex: 1, alignItems: "center", gap: 4 },
  weekday: { ...font.caption, color: colors.textMuted },
  day: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  daySelected: { backgroundColor: colors.surfaceStrong },
  dayText: { ...font.bodyStrong, color: colors.textSub },
  today: { color: colors.text, fontWeight: "800" },
});
