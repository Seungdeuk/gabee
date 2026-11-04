import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { WEEKDAYS } from "../../constants";
import { addDays, formatYearMonth, fromDateKey, todayKey } from "../../utils/date";
import { monthWeeks } from "../../month_grid";
import BottomSheet from "../../components/BottomSheet";
import BlockInput from "../../components/BlockInput";
import { SELECT_BG, canShiftMonth, isRecordableDay, shiftMonthView, typedDateOf } from "../logic";

const DATE_BLOCKS = [
  { key: "y", length: 4, hint: "YYYY", min: 1900, max: 2999 },
  { key: "m", length: 2, hint: "MM", min: 1, max: 12, padAbove: 1 },
  { key: "d", length: 2, hint: "DD", min: 1, max: 31, padAbove: 3 },
];
const EMPTY = ["", "", ""];
const WEEK_FROM_MONDAY = [...WEEKDAYS.slice(1), WEEKDAYS[0]]; // 월~일

/**
 * 날짜 고르기 시트. 일정 등록의 날짜 시트와 같은 모양으로, 위에 빠른 선택 줄(오늘·어제·직접 지정), 아래 월 달력(월요일 시작, 그 달에 필요한 줄만)을 둔다.
 * 기록할 수 있는 날짜는 오늘 ~ 7일 전뿐이라 그 밖의 칸은 흐리게 두고 누르지 않는다. 달 화살표도 옮길 달에 기록할 날이 없으면 막는다.
 * "직접 지정"을 누르면 YYYY-MM-DD 입력 칸으로 바뀌고 "빠르게 고르기"로 돌아온다. 입력 칸과 달력은 서로 연동된다.
 * 시트가 열릴 때마다 지금 보고 있는 날짜(selected)로 다시 맞춘다. [선택]을 누르면 onPick(날짜 키)을 부르고, 닫는 일은 호출하는 쪽이 한다.
 * @param {{ visible: boolean, onClose: () => void, selected: string, onPick: (dateKey: string) => void }} props selected 는 "YYYY-MM-DD"
 */
export default function DayPickSheet({ visible, onClose, selected, onPick }) {
  const today = todayKey();
  const [draft, setDraft] = useState(selected); // 고른 날짜
  const [view, setView] = useState(selected); // 달력이 보고 있는 달(날짜 키 아무거나. 화살표로만 바뀐다)
  const [typing, setTyping] = useState(false);
  const [blocks, setBlocks] = useState(EMPTY);
  // 시트가 열릴 때마다 보고 있는 날짜로 맞춘다. 열린 채로 남은 이전 상태를 버리려고 렌더 중에 비교한다(useEffect 는 한 프레임 늦게 바뀐다).
  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) {
      setDraft(selected);
      setView(selected);
      setTyping(false);
      setBlocks(EMPTY);
    }
  }

  // 달력(날짜)에서 고르면 직접 입력 칸의 숫자도 그 날짜로 바뀐다.
  const pick = (key) => {
    setDraft(key);
    setView(key);
    if (typing) setBlocks(key.split("-"));
  };
  // 입력 칸을 칠 때마다 검증한다. 기록할 수 있는 날짜면 draft 와 달력이 따라가고, 아니면 draft 는 그대로 둔다.
  const type = (next) => {
    setBlocks(next);
    const { key } = typedDateOf(next, today);
    if (key) {
      setDraft(key);
      setView(key);
    }
  };
  const typed = typedDateOf(blocks, today);
  const closeTyping = () => {
    setTyping(false);
    setBlocks(EMPTY);
  };
  const quick = [
    { label: "오늘", date: today },
    { label: "어제", date: addDays(today, -1) },
  ];
  const shown = fromDateKey(view);
  const rows = monthWeeks(shown.getFullYear(), shown.getMonth() + 1); // 월요일 시작, 그 달에 필요한 줄만
  const prevOk = canShiftMonth(view, -1, today);
  const nextOk = canShiftMonth(view, 1, today);

  return (
    <BottomSheet visible={visible} onClose={onClose}>
      <Text style={styles.title} accessibilityRole="header">
        날짜 고르기
      </Text>
      {typing ? (
        <View style={styles.typeBox}>
          <BlockInput blocks={DATE_BLOCKS} separators={["-", "-"]} values={blocks} onChange={type} autoFocus large />
          {typed.message ? <Text style={styles.invalid}>{typed.message}</Text> : null}
          <View style={styles.typeActions}>
            <DayChip label="빠르게 고르기" muted onPress={closeTyping} />
          </View>
        </View>
      ) : (
        <View style={styles.quick}>
          {quick.map((q) => (
            <DayChip key={q.label} label={q.label} selected={draft === q.date} onPress={() => pick(q.date)} />
          ))}
          <DayChip
            label="직접 지정"
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
          <Text style={styles.month}>{formatYearMonth(view)}</Text>
          <View style={styles.arrows}>
            <Pressable
              onPress={() => setView(shiftMonthView(view, -1))}
              disabled={!prevOk}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel="이전 달"
              accessibilityState={{ disabled: !prevOk }}
            >
              <Text style={[styles.arrow, !prevOk && styles.off]}>‹</Text>
            </Pressable>
            <Pressable
              onPress={() => setView(shiftMonthView(view, 1))}
              disabled={!nextOk}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel="다음 달"
              accessibilityState={{ disabled: !nextOk }}
            >
              <Text style={[styles.arrow, !nextOk && styles.off]}>›</Text>
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
            {row.map((key, i) => {
              if (!key) return <View key={`blank-${i}`} style={styles.cellBox} />;
              const ok = isRecordableDay(key, today);
              const on = key === draft;
              return (
                <Pressable
                  key={key}
                  onPress={() => pick(key)}
                  disabled={!ok}
                  style={styles.cellBox}
                  accessibilityRole="button"
                  accessibilityState={{ selected: on, disabled: !ok }}
                >
                  <View collapsable={false} style={[styles.cell, on && styles.selected]}>
                    <Text style={[styles.date, !ok && styles.off, on && styles.dateSelected]}>{fromDateKey(key).getDate()}</Text>
                  </View>
                </Pressable>
              );
            })}
          </View>
        ))}
      </View>

      <Pressable onPress={() => onPick(draft)} style={styles.save} accessibilityRole="button">
        <Text style={styles.saveText}>선택</Text>
      </Pressable>
    </BottomSheet>
  );
}

/** 빠른 선택 칩: 평소에는 흰 바탕·옅은 테두리, 지금 고른 날짜는 노란 바탕과 굵은 글자(테두리도 같은 노랑). muted 는 옅은 글자(직접 지정·빠르게 고르기). */
function DayChip({ label, selected = false, muted = false, onPress }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected }} style={[styles.chip, selected && styles.chipOn]}>
      <Text style={[styles.chipText, muted && styles.chipMuted, selected && styles.chipTextOn]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: { paddingHorizontal: 11, paddingVertical: 4, borderRadius: radius.pill, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: SELECT_BG, borderColor: SELECT_BG },
  chipMuted: { color: colors.textMuted },
  chipText: { fontSize: 13, fontWeight: "500", color: colors.text },
  chipTextOn: { fontWeight: "700" },
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
  // 기록할 수 없는 칸·움직일 수 없는 화살표는 흐리게(누르면 반응 없음).
  off: { color: colors.disabled },
  week: { flexDirection: "row" },
  weekday: { flex: 1, textAlign: "center", ...font.caption, color: colors.textMuted },
  cellBox: { flex: 1, alignItems: "center", paddingVertical: 1 },
  cell: { width: 40, height: 42, borderRadius: 14, alignItems: "center", justifyContent: "center" },
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
