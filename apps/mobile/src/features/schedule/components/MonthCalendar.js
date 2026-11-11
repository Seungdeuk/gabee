import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { dotsFor } from "../calendar";
import { DOT_COLOR, KIND, SELECTED_TODO_DOT, WEEKDAYS } from "../constants";
import { firstDayLabel } from "../lunar";
import { fromDateKey, monthCells, formatYearMonth, weekOf } from "../utils/date";

const WEEK_FROM_MONDAY = [...WEEKDAYS.slice(1), WEEKDAYS[0]]; // 월~일
const chunk = (cells) => Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));

/**
 * 월 달력. 날짜마다 점(약속 복숭아, 할 일 초록, 최대 3개)을 찍고 선택한 날짜는 갈색 바탕.
 * 음력 1일(초하루)인 칸에는 날짜 아래에 "10.1" 같은 작은 글자를 항상 보여 준다(윤달은 "윤 10.1", 켜고 끄는 스위치는 없다).
 * 월요일부터 시작하고, 접으면 선택한 날짜의 한 주(월~일) 한 줄만 보인다. 접기·펴기는 드래그가 아니라 버튼.
 * @param {{ selected: string, marks: Map<string, { appointment: number, todo: number }>, collapsed: boolean, onSelect: (dateKey: string) => void, onShift: (delta: number) => void, onToggleCollapse: () => void }} props
 *   onShift 는 펼침에서는 달, 접힘에서는 주 단위로 옮긴다(부모가 정한다).
 */
export default function MonthCalendar({ selected, marks, collapsed, onSelect, onShift, onToggleCollapse }) {
  const d = fromDateKey(selected);
  const cells = collapsed ? weekOf(selected) : monthCells(d.getFullYear(), d.getMonth() + 1);
  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.month}>{formatYearMonth(selected)}</Text>
        <View style={styles.right}>
          <View style={styles.legend}>
            <Legend color={DOT_COLOR} label="약속" />
            <Legend color={colors.success} label="할 일" />
          </View>
          <Pressable onPress={() => onShift(-1)} hitSlop={8} accessibilityLabel="이전">
            <Ionicons name="chevron-back" size={20} color={colors.textMuted} />
          </Pressable>
          <Pressable onPress={() => onShift(1)} hitSlop={8} accessibilityLabel="다음">
            <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
          </Pressable>
        </View>
      </View>
      <View style={styles.week}>
        {WEEK_FROM_MONDAY.map((name) => (
          <Text key={name} style={styles.weekday}>
            {name}
          </Text>
        ))}
      </View>
      {chunk(cells).map((row, index) => (
        <View key={index} style={styles.week}>
          {row.map((key, i) => (
            <Day key={key ?? `blank-${i}`} dateKey={key} selected={key === selected} mark={marks.get(key)} onSelect={onSelect} />
          ))}
        </View>
      ))}
      <Pressable onPress={onToggleCollapse} style={styles.handle} accessibilityRole="button">
        <View style={styles.handlePill}>
          <View style={styles.handleBar} />
          <Text style={styles.handleText}>{collapsed ? "펴기" : "접기"}</Text>
        </View>
      </Pressable>
    </View>
  );
}

function Legend({ color, label }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text style={styles.legendText}>{label}</Text>
    </View>
  );
}

function Day({ dateKey, selected, mark, onSelect }) {
  if (!dateKey) return <View style={styles.cell} />;
  const first = firstDayLabel(dateKey);
  return (
    <Pressable onPress={() => onSelect(dateKey)} style={[styles.cell, styles.day, selected && styles.daySelected]}>
      <Text style={[styles.date, selected && styles.dateSelected]}>{fromDateKey(dateKey).getDate()}</Text>
      <Text style={[styles.lunar, selected && styles.lunarSelected]} numberOfLines={1}>
        {first ?? " "}
      </Text>
      <View style={styles.dots}>
        {dotsFor(mark).map((kind, i) => (
          <View
            key={i}
            style={[
              styles.dot,
              { backgroundColor: kind === KIND.appointment ? (selected ? colors.peach : DOT_COLOR) : selected ? SELECTED_TODO_DOT : colors.success },
            ]}
          />
        ))}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: spacing.sm,
    paddingTop: 14,
    paddingBottom: spacing.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
    shadowColor: colors.text,
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 6 },
  month: { ...font.title, color: colors.text },
  right: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  legend: { flexDirection: "row", gap: spacing.sm },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  legendDot: { width: 6, height: 6, borderRadius: 3 },
  legendText: { fontSize: 12, color: colors.textMuted },
  week: { flexDirection: "row" },
  weekday: { flex: 1, textAlign: "center", ...font.caption, color: colors.textMuted, paddingBottom: 2 },
  cell: { flex: 1 },
  day: { alignItems: "center", gap: 1, paddingTop: 5, paddingBottom: 4, borderRadius: 14 },
  daySelected: { backgroundColor: colors.text },
  date: { fontSize: 15, color: colors.text },
  dateSelected: { color: colors.background },
  lunar: { fontSize: 9, lineHeight: 11, color: colors.accent, fontWeight: "700", letterSpacing: -0.2 },
  lunarSelected: { color: colors.surfaceStrong },
  dots: { flexDirection: "row", gap: 2, height: 5 },
  dot: { width: 4, height: 4, borderRadius: 2 },
  handle: { alignItems: "center", paddingTop: 2 },
  handlePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 3,
    paddingLeft: 10,
    paddingRight: spacing.md,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
  },
  handleBar: { width: 12, height: 3, borderRadius: 3, backgroundColor: colors.textMuted },
  handleText: { fontSize: 12, color: colors.textMuted },
});
