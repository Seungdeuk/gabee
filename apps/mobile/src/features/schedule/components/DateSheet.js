import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { WEEKDAYS } from "../constants";
import { addDays, formatYearMonth, fromDateKey, nextWeekday, shiftMonthKey, todayKey } from "../utils/date";
import { monthWeeks } from "../month_grid";
import { dateFromBlocks } from "../utils/time";
import BottomSheet from "./BottomSheet";
import FilterChip from "./FilterChip";
import BlockInput from "./BlockInput";

const DATE_BLOCKS = [
  { key: "y", length: 4, hint: "YYYY", min: 1900, max: 2999 },
  { key: "m", length: 2, hint: "MM", min: 1, max: 12, padAbove: 1 },
  { key: "d", length: 2, hint: "DD", min: 1, max: 31, padAbove: 3 },
];
const EMPTY = ["", "", ""];
const WEEK_FROM_MONDAY = [...WEEKDAYS.slice(1), WEEKDAYS[0]]; // 월~일

/**
 * 날짜 선택 시트: 빠른 선택 줄(오늘·내일·토요일·일요일) + 월 달력(월요일부터, 그 달에 필요한 줄만) + 선택 버튼.
 * 토·일은 이번 주 기준이고 이미 지났으면 다음 주다. "직접 입력"을 누르면 그 줄이 YYYY-MM-DD 입력 칸으로 바뀌고,
 * "빠르게 고르기"를 누르면 다시 빠른 선택 줄로 돌아온다. 입력 칸과 달력은 서로 연동돼서 한쪽에서 고르면 다른 쪽도 바뀐다.
 * 연도까지 받아서 작년·내년도 쓸 수 있다. 연·월·일 영역을 터치하면 영역이 선택되고 숫자를 치면 그 영역이 새로 채워진다
 * (월에서 9 → 09처럼 첫 숫자가 크면 0을 붙여 바로 다음 영역으로 간다). 올바른 날짜가 되면 아래 달력이 바로 그 날짜로 이동해 선택된다.
 * @param {{ visible: boolean, value: string, onClose: () => void, onSelect: (dateKey: string) => void }} props value 는 지금 고른 날짜("YYYY-MM-DD", 없으면 빈 글자)
 */
export default function DateSheet({ visible, value, onClose, onSelect }) {
  const today = todayKey();
  const [draft, setDraft] = useState(value || today);
  const [typing, setTyping] = useState(false);
  const [blocks, setBlocks] = useState(EMPTY);
  const type = (next) => {
    setBlocks(next);
    const parsed = dateFromBlocks(next[0], next[1], next[2]);
    if (parsed) setDraft(parsed);
  };
  // 달력(날짜·달 이동)에서 고르면 직접 입력 칸의 숫자도 그 날짜로 바뀐다.
  const pick = (key) => {
    setDraft(key);
    if (typing) setBlocks(key.split("-"));
  };
  const complete = blocks[0].length === 4 && blocks[1].length === 2 && blocks[2].length === 2;
  const invalid = complete && dateFromBlocks(blocks[0], blocks[1], blocks[2]) === null;
  const closeTyping = () => {
    setTyping(false);
    setBlocks(EMPTY);
  };
  const quick = [
    { label: "오늘", date: today },
    { label: "내일", date: addDays(today, 1) },
    { label: "토요일", date: nextWeekday(today, 6) },
    { label: "일요일", date: nextWeekday(today, 0) },
  ];
  const month = fromDateKey(draft);
  const rows = monthWeeks(month.getFullYear(), month.getMonth() + 1); // 월요일 시작, 그 달에 필요한 줄만

  return (
    <BottomSheet visible={visible} onClose={onClose}>
      <Text style={styles.title}>날짜</Text>
      {typing ? (
        <View style={styles.typeBox}>
          <BlockInput blocks={DATE_BLOCKS} separators={["-", "-"]} values={blocks} onChange={type} autoFocus large />
          {invalid ? <Text style={styles.invalid}>없는 날짜예요</Text> : null}
          <View style={styles.typeActions}>
            <FilterChip label="빠르게 고르기" muted onPress={closeTyping} />
            <FilterChip label="오늘" selected={draft === today} onPress={() => pick(today)} />
          </View>
        </View>
      ) : (
        <View style={styles.quick}>
          {quick.map((q) => (
            <FilterChip key={q.label} label={q.label} selected={draft === q.date} onPress={() => pick(q.date)} />
          ))}
          <FilterChip
            label="직접 입력"
            muted
            onPress={() => {
              setBlocks(EMPTY);
              setTyping(true);
            }}
          />
        </View>
      )}

      <View style={styles.calendar}>
        <View style={styles.monthRow}>
          <Text style={styles.month}>{formatYearMonth(draft)}</Text>
          <View style={styles.arrows}>
            <Pressable onPress={() => pick(shiftMonthKey(draft, -1))} hitSlop={8} accessibilityLabel="이전 달">
              <Text style={styles.arrow}>‹</Text>
            </Pressable>
            <Pressable onPress={() => pick(shiftMonthKey(draft, 1))} hitSlop={8} accessibilityLabel="다음 달">
              <Text style={styles.arrow}>›</Text>
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
        {rows.map((row, r) => (
          <View key={r} style={styles.week}>
            {row.map((key, i) =>
              key ? (
                <Pressable key={key} onPress={() => pick(key)} style={styles.cellBox} accessibilityRole="button">
                  <View style={[styles.cell, key === draft && styles.selected]}>
                    <Text style={[styles.date, key === draft && styles.dateSelected]}>{fromDateKey(key).getDate()}</Text>
                  </View>
                </Pressable>
              ) : (
                <View key={`blank-${i}`} style={styles.cellBox} />
              ),
            )}
          </View>
        ))}
      </View>

      <Pressable onPress={() => onSelect(draft)} style={styles.save} accessibilityRole="button">
        <Text style={styles.saveText}>선택</Text>
      </Pressable>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text, marginBottom: -4 },
  quick: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  typeBox: { gap: spacing.sm },
  typeActions: { flexDirection: "row", alignItems: "center", gap: 5 },
  invalid: { ...font.caption, color: colors.danger, textAlign: "center" },
  calendar: { gap: 2 },
  monthRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  month: { fontSize: 18, fontWeight: "700", color: colors.text },
  arrows: { flexDirection: "row", gap: spacing.lg },
  arrow: { fontSize: 22, color: colors.textMuted },
  week: { flexDirection: "row" },
  weekday: { flex: 1, textAlign: "center", ...font.caption, color: colors.textMuted },
  cellBox: { flex: 1, alignItems: "center", paddingVertical: 1 },
  cell: { width: 40, height: 36, borderRadius: 14, alignItems: "center", justifyContent: "center" },
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
