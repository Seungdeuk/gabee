import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius } from "@/theme";

import { DOT_COLOR, WEEKDAYS } from "../constants";
import { fromDateKey, todayKey, weekOf } from "../utils/date";

/**
 * 한 주(월~일) 날짜 줄. 오늘은 갈색 바탕에 밝은 글자, 일정 있는 날은 아래에 점.
 * @param {{ selected: string, markedDates?: Set<string>, onSelect?: (dateKey: string) => void }} props
 */
export default function WeekStrip({ selected, markedDates, onSelect }) {
  const today = todayKey();
  return (
    <View style={styles.row}>
      {weekOf(selected).map((key) => {
        const d = fromDateKey(key);
        const isToday = key === today;
        return (
          <Pressable
            key={key}
            onPress={() => onSelect?.(key)}
            style={[styles.day, isToday && styles.today]}
            accessibilityRole="button"
          >
            <Text style={[styles.weekday, isToday && styles.todayText]}>{WEEKDAYS[d.getDay()]}</Text>
            <Text style={[styles.date, isToday && styles.todayDate]}>{d.getDate()}</Text>
            <View
              style={[
                styles.dot,
                markedDates?.has(key) && { backgroundColor: isToday ? colors.peach : DOT_COLOR },
              ]}
            />
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
  today: { backgroundColor: colors.text },
  weekday: { ...font.caption, color: colors.textMuted },
  date: { fontSize: 17, fontWeight: "500", color: colors.text },
  todayText: { color: colors.background },
  todayDate: { color: colors.background, fontWeight: "700" },
  dot: { width: 4, height: 4, borderRadius: 2 },
});
