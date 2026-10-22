import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { DOT_COLOR, WEEKDAYS } from "../constants";
import { addDays, formatYearMonth, fromDateKey, monthCells, nextWeekday, shiftMonthKey, todayKey } from "../utils/date";
import BottomSheet from "./BottomSheet";
import FilterChip from "./FilterChip";

/**
 * 날짜 선택 시트: 빠른 선택 줄(오늘·내일·토요일·일요일) + 월 달력 + 선택 버튼.
 * 토·일은 이번 주 기준이고 이미 지났으면 다음 주다. "직접 입력"은 다음 PR에서 붙인다.
 * @param {{ visible: boolean, value: string, onClose: () => void, onSelect: (dateKey: string) => void }} props value 는 지금 고른 날짜("YYYY-MM-DD", 없으면 빈 글자)
 */
export default function DateSheet({ visible, value, onClose, onSelect }) {
  const today = todayKey();
  const [draft, setDraft] = useState(value || today);
  const quick = [
    { label: "오늘", date: today },
    { label: "내일", date: addDays(today, 1) },
    { label: "토요일", date: nextWeekday(today, 6) },
    { label: "일요일", date: nextWeekday(today, 0) },
  ];
  const month = fromDateKey(draft);
  const cells = monthCells(month.getFullYear(), month.getMonth() + 1);

  return (
    <BottomSheet visible={visible} onClose={onClose}>
      <Text style={styles.title}>날짜</Text>
      <View style={styles.quick}>
        {quick.map((q) => (
          <FilterChip key={q.label} label={q.label} selected={draft === q.date} onPress={() => setDraft(q.date)} />
        ))}
        <FilterChip label="직접 입력" muted />
      </View>

      <View style={styles.monthRow}>
        <Text style={styles.month}>{formatYearMonth(draft)}</Text>
        <View style={styles.arrows}>
          <Pressable onPress={() => setDraft(shiftMonthKey(draft, -1))} hitSlop={8} accessibilityLabel="이전 달">
            <Text style={styles.arrow}>‹</Text>
          </Pressable>
          <Pressable onPress={() => setDraft(shiftMonthKey(draft, 1))} hitSlop={8} accessibilityLabel="다음 달">
            <Text style={styles.arrow}>›</Text>
          </Pressable>
        </View>
      </View>
      <View style={styles.week}>
        {WEEKDAYS.map((name) => (
          <Text key={name} style={styles.weekday}>
            {name}
          </Text>
        ))}
      </View>
      <View style={styles.grid}>
        {cells.map((key, i) =>
          key ? (
            <Pressable key={key} onPress={() => setDraft(key)} style={styles.cellBox} accessibilityRole="button">
              <View style={[styles.cell, key === today && styles.today, key === draft && styles.selected]}>
                <Text style={[styles.date, key === draft && styles.dateSelected]}>{fromDateKey(key).getDate()}</Text>
              </View>
            </Pressable>
          ) : (
            <View key={`blank-${i}`} style={styles.cellBox} />
          ),
        )}
      </View>

      <Pressable onPress={() => onSelect(draft)} style={styles.save} accessibilityRole="button">
        <Text style={styles.saveText}>선택</Text>
      </Pressable>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  quick: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  monthRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  month: { fontSize: 18, fontWeight: "700", color: colors.text },
  arrows: { flexDirection: "row", gap: spacing.lg },
  arrow: { fontSize: 22, color: colors.textMuted },
  week: { flexDirection: "row" },
  weekday: { flex: 1, textAlign: "center", ...font.caption, color: colors.textMuted },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  cellBox: { width: `${100 / 7}%`, alignItems: "center", paddingVertical: 1 },
  cell: { width: 40, height: 36, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  today: { borderWidth: 1.5, borderColor: DOT_COLOR },
  selected: { backgroundColor: colors.text },
  date: { fontSize: 15, color: colors.text },
  dateSelected: { color: colors.background, fontWeight: "700" },
  save: {
    minHeight: 56,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.button,
    backgroundColor: colors.peach,
  },
  saveText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
