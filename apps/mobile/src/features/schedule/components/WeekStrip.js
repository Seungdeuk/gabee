import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius } from "@/theme";

import { EVENT_DOT_COLOR, WEEKDAYS } from "../constants";
import { fromDateKey, todayKey, weekOf } from "../utils/date";

/**
 * 한 주(월~일) 날짜 줄. 고른 날은 갈색 바탕에 밝은 글자, 오늘(고르지 않았을 때)은 옅은 복숭아 바탕, 일정 있는 날은 아래에 복숭아색 동그라미 점.
 * @param {{ selected: string, markedDates?: Set<string>, onSelect?: (dateKey: string) => void }} props
 */
export default function WeekStrip({ selected, markedDates, onSelect }) {
  const today = todayKey();
  return (
    <View style={styles.row}>
      {weekOf(selected).map((key) => {
        const d = fromDateKey(key);
        const isSelected = key === selected;
        const isToday = key === today;
        return (
          <Pressable
            key={key}
            onPress={() => onSelect?.(key)}
            style={[styles.day, isToday && !isSelected && styles.today, isSelected && styles.selected]}
            accessibilityRole="button"
            accessibilityState={{ selected: isSelected }}
          >
            <Text style={[styles.weekday, isSelected && styles.selectedText]}>{WEEKDAYS[d.getDay()]}</Text>
            <Text style={[styles.date, (isSelected || isToday) && styles.dateStrong, isSelected && styles.selectedText]}>{d.getDate()}</Text>
            <View style={[styles.dot, markedDates?.has(key) && { backgroundColor: EVENT_DOT_COLOR }]} />
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 4 },
  day: {
    flex: 1,
    alignItems: "center",
    gap: 2,
    paddingTop: 9,
    paddingBottom: 8,
    borderRadius: radius.button,
  },
  today: { backgroundColor: colors.peachSoft },
  selected: { backgroundColor: colors.text },
  weekday: { ...font.caption, color: colors.textMuted },
  date: { fontSize: 17, fontWeight: "500", color: colors.text },
  dateStrong: { fontWeight: "700" },
  selectedText: { color: colors.background },
  dot: { width: 6, height: 6, borderRadius: 3, overflow: "hidden" },
});
