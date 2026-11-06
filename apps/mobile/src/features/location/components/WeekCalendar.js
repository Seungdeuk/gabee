import { useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

import { calendarWeek, KEEP_DAYS, todayKst, weekTitle } from "../timelineView";

const WEEKS = [
  { key: "0", label: "이번 주" },
  { key: "1", label: "지난 주" },
];

/**
 * 일주일 달력(일요일 시작). 이번 주/지난 주를 알약으로 바꾸고, 날짜 칸을 한 번 눌러 고른다.
 * 오늘 이후와 보관 기간(14일)이 지난 날은 누를 수 없다.
 * @param {{ date: string, onChange: (date: string) => void, today?: string }} props
 */
export default function WeekCalendar({ date, onChange, today = todayKst() }) {
  const thisWeek = calendarWeek(today, 0);
  const weekOffset = thisWeek.some((d) => d.date === date) ? 0 : 1;
  const week = useMemo(() => calendarWeek(today, weekOffset), [today, weekOffset]);

  /** 주를 바꾸면 그 주에서 고를 수 있는 날(이번 주는 오늘, 지난 주는 그 주의 마지막 날)로 옮긴다. */
  const changeWeek = (key) => {
    const target = calendarWeek(today, Number(key));
    const open = target.filter((d) => d.state === "open");
    if (open.length) onChange(open[open.length - 1].date);
  };

  return (
    <View style={styles.wrap}>
      <Segmented options={WEEKS} value={String(weekOffset)} onChange={changeWeek} />
      <Text style={styles.title}>{weekTitle(week)}</Text>
      <View style={styles.row}>
        {week.map((d) => {
          const selected = d.date === date;
          const off = d.state !== "open";
          return (
            <Pressable
              key={d.date}
              onPress={() => onChange(d.date)}
              disabled={off}
              accessibilityRole="button"
              accessibilityState={{ selected, disabled: off }}
              accessibilityLabel={`${Number(d.date.slice(5, 7))}월 ${d.day}일 ${d.weekday}요일`}
              style={[styles.cell, selected && styles.cellOn, off && styles.cellOff]}
              testID={`week-day-${d.date}`}
            >
              <Text style={[styles.weekday, selected && styles.textOn]}>{d.weekday}</Text>
              <Text style={[styles.day, selected && styles.textOn]}>{d.day}</Text>
              <View style={[styles.dot, d.isToday && (selected ? styles.dotOnDark : styles.dotToday)]} />
            </Pressable>
          );
        })}
      </View>
      <Text style={styles.note}>위치 기록은 {KEEP_DAYS}일이 지나면 지워요</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 10 },
  title: { ...font.bodyStrong, color: colors.text, textAlign: "center" },
  row: { flexDirection: "row", gap: 4 },
  cell: { flex: 1, minHeight: 64, borderRadius: 14, alignItems: "center", justifyContent: "center", gap: 2, backgroundColor: colors.surface },
  cellOn: { backgroundColor: colors.dark },
  cellOff: { opacity: 0.35 },
  weekday: { ...font.caption, color: colors.textMuted },
  day: { ...font.bodyStrong, color: colors.text },
  textOn: { color: colors.onDark },
  dot: { width: 5, height: 5, borderRadius: 3 },
  dotToday: { backgroundColor: colors.accent },
  dotOnDark: { backgroundColor: colors.onDark },
  note: { ...font.caption, fontSize: 11, color: colors.textMuted, textAlign: "center" },
});
