import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { WEEKDAYS } from "../constants";
import { firstDayLabel, lunarToSolar, solarToLunar } from "../lunar";
import { addDays, formatYearMonth, fromDateKey, nextWeekday, shiftMonthKey, todayKey } from "../utils/date";
import { monthWeeks } from "../month_grid";
import { dateFromBlocks } from "../utils/time";
import BottomSheet from "./BottomSheet";
import FilterChip from "./FilterChip";
import BlockInput from "./BlockInput";
import LunarToggle from "./LunarToggle";

const DATE_BLOCKS = [
  { key: "y", length: 4, hint: "YYYY", min: 1900, max: 2999 },
  { key: "m", length: 2, hint: "MM", min: 1, max: 12, padAbove: 1 },
  { key: "d", length: 2, hint: "DD", min: 1, max: 31, padAbove: 3 },
];
const EMPTY = ["", "", ""];
const pad2 = (n) => String(n).padStart(2, "0");
// 달력(양력) 날짜를 입력 칸에 넣을 값(연, 월, 일)과 윤달 여부로 바꾼다. 음력 입력이면 그 날의 음력, 변환할 수 없으면 양력 그대로.
function fieldsOf(key, lunar) {
  if (!lunar) return { values: key.split("-"), leap: false };
  const l = solarToLunar(key);
  return l ? { values: [String(l.year), pad2(l.month), pad2(l.day)], leap: l.leap } : { values: key.split("-"), leap: false };
}
// 음력 칸의 연·월·일이 가리키는 평달 날짜와 윤달 날짜(양력). 덜 쳤거나 없는 날짜면 null. 윤달 날짜는 그 해 그 달에 윤달이 있고 그 날이 있을 때만 있다.
function lunarCandidates(values) {
  if (!/^\d{4}$/.test(values[0]) || !/^\d{2}$/.test(values[1]) || !/^\d{2}$/.test(values[2])) return { normal: null, leap: null };
  const [y, m, d] = values.map(Number);
  return { normal: lunarToSolar(y, m, d, false), leap: lunarToSolar(y, m, d, true) };
}
// 입력 칸의 연·월·일을 양력 날짜로. 양력 입력이면 그대로, 음력 입력이면 변환한다(윤달을 골랐고 그 윤달 날짜가 있으면 윤달). 덜 쳤거나 없는 날짜면 null.
function solarOf(values, lunar, leap) {
  if (!lunar) return dateFromBlocks(values[0], values[1], values[2]);
  const c = lunarCandidates(values);
  return leap && c.leap ? c.leap : c.normal;
}
function shortDate(key) {
  const d = fromDateKey(key);
  return `${d.getMonth() + 1}/${d.getDate()}(${WEEKDAYS[d.getDay()]})`;
}
const WEEK_FROM_MONDAY = [...WEEKDAYS.slice(1), WEEKDAYS[0]]; // 월~일

/**
 * 날짜 선택 시트: 빠른 선택 줄(오늘·내일·토요일·일요일) + 월 달력(월요일부터, 그 달에 필요한 줄만) + 선택 버튼.
 * 토·일은 이번 주 기준이고 이미 지났으면 다음 주다. "직접 입력"을 누르면 그 줄이 YYYY-MM-DD 입력 칸으로 바뀌고,
 * "빠르게 고르기"를 누르면 다시 빠른 선택 줄로 돌아온다. 입력 칸과 달력은 서로 연동돼서 한쪽에서 고르면 다른 쪽도 바뀐다.
 * 직접 입력일 때만 입력 칸 오른쪽 끝에 양력/음력 스위치가 나타난다(기본 양력). 스위치를 바꿔도 칸의 숫자는 그대로이고 "그 숫자를 음력(양력)으로 본다"만 바뀌며,
 * 아래 달력이 그에 해당하는 양력 날짜를 가리킨다. 음력으로 입력한 날짜가 평달과 윤달 둘 다 있으면(예: 2025년 6월 1일과 윤6월 1일) 그때만 "6월 1일 / 윤6월 1일" 두 칸이
 * 양력 날짜와 함께 나와 고르게 한다(기본 평달). 양력일 때나 윤달이 겹치지 않을 때는 나오지 않는다. 선택되는 값(onSelect)은 항상 양력이다. "빠르게 고르기"로 돌아가면 양력으로 돌아온다.
 * 달력 칸에는 음력 1일(초하루)이면 날짜 아래에 "10.1"(윤달은 "윤 10.1")이 작게 보인다.
 * 연도까지 받아서 작년·내년도 쓸 수 있다. 연·월·일 영역을 터치하면 영역이 선택되고 숫자를 치면 그 영역이 새로 채워진다
 * (월에서 9 → 09처럼 첫 숫자가 크면 0을 붙여 바로 다음 영역으로 간다). 올바른 날짜가 되면 아래 달력이 바로 그 날짜로 이동해 선택된다.
 * @param {{ visible: boolean, value: string, onClose: () => void, onSelect: (dateKey: string) => void }} props value 는 지금 고른 날짜("YYYY-MM-DD", 없으면 빈 글자)
 */
export default function DateSheet({ visible, value, onClose, onSelect }) {
  const today = todayKey();
  const [draft, setDraft] = useState(value || today);
  const [typing, setTyping] = useState(false);
  const [blocks, setBlocks] = useState(EMPTY);
  const [lunar, setLunar] = useState(false);
  const [leap, setLeap] = useState(false);
  const type = (next) => {
    setBlocks(next);
    // 윤달을 고른 상태에서 윤달이 겹치지 않는 날짜로 바뀌면 선택을 풀어 둔다(다시 겹치면 평달부터).
    const c = lunar ? lunarCandidates(next) : { normal: null, leap: null };
    const stillAsks = Boolean(c.normal && c.leap);
    if (!stillAsks && leap) setLeap(false);
    const parsed = solarOf(next, lunar, stillAsks && leap);
    if (parsed) setDraft(parsed);
  };
  const chooseLeap = (next) => {
    setLeap(next);
    const parsed = solarOf(blocks, true, next);
    if (parsed) setDraft(parsed);
  };
  // 달력(날짜·달 이동)에서 고르면 직접 입력 칸의 숫자도 그 날짜로 바뀐다(음력 입력이면 그 날의 음력으로).
  const pick = (key) => {
    setDraft(key);
    if (typing) {
      const f = fieldsOf(key, lunar);
      setBlocks(f.values);
      setLeap(f.leap);
    }
  };
  // 스위치를 바꿔도 칸의 숫자는 그대로 두고, 그 숫자가 가리키는 양력 날짜로 달력만 옮긴다.
  const switchLunar = (next) => {
    setLunar(next);
    const parsed = solarOf(blocks, next, leap);
    if (parsed) setDraft(parsed);
  };
  const complete = blocks[0].length === 4 && blocks[1].length === 2 && blocks[2].length === 2;
  const invalid = complete && solarOf(blocks, lunar, leap) === null;
  // 음력 입력이 평달·윤달 둘 다 가능하면 두 칸으로 고르게 한다.
  const candidates = lunar ? lunarCandidates(blocks) : { normal: null, leap: null };
  const askLeap = Boolean(candidates.normal && candidates.leap);
  const closeTyping = () => {
    setTyping(false);
    setBlocks(EMPTY);
    setLunar(false);
    setLeap(false);
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
          <BlockInput
            blocks={DATE_BLOCKS}
            separators={["-", "-"]}
            values={blocks}
            onChange={type}
            autoFocus
            large
            trailing={<LunarToggle lunar={lunar} onChange={switchLunar} />}
          />
          {invalid ? <Text style={styles.invalid}>없는 날짜예요</Text> : null}
          {askLeap ? (
            <View style={styles.leapRow}>
              <LeapCard title={`${Number(blocks[1])}월 ${Number(blocks[2])}일`} solar={shortDate(candidates.normal)} selected={!leap} onPress={() => chooseLeap(false)} />
              <LeapCard title={`윤${Number(blocks[1])}월 ${Number(blocks[2])}일`} solar={shortDate(candidates.leap)} selected={leap} onPress={() => chooseLeap(true)} />
            </View>
          ) : null}
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
                  <View collapsable={false} style={[styles.cell, key === draft && styles.selected]}>
                    <Text style={[styles.date, key === draft && styles.dateSelected]}>{fromDateKey(key).getDate()}</Text>
                    <Text style={[styles.lunar, key === draft && styles.lunarSelected]} numberOfLines={1}>
                      {firstDayLabel(key) ?? " "}
                    </Text>
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

function LeapCard({ title, solar, selected, onPress }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected }} style={[styles.leapCard, selected && styles.leapCardOn]}>
      <Text style={styles.leapTitle}>{title}</Text>
      <Text style={styles.leapSolar}>{`양력 ${solar}`}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text, marginBottom: -4 },
  quick: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  typeBox: { gap: spacing.sm },
  typeActions: { flexDirection: "row", alignItems: "center", gap: 5 },
  invalid: { ...font.caption, color: colors.danger, textAlign: "center" },
  leapRow: { flexDirection: "row", gap: spacing.sm },
  leapCard: { flex: 1, paddingVertical: 9, paddingHorizontal: spacing.md, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.card },
  leapCardOn: { borderColor: colors.text, backgroundColor: colors.surfaceStrong },
  leapTitle: { ...font.bodyStrong, color: colors.text },
  leapSolar: { ...font.caption, color: colors.textMuted },
  calendar: { gap: 2 },
  monthRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  month: { fontSize: 18, fontWeight: "700", color: colors.text },
  arrows: { flexDirection: "row", gap: spacing.lg },
  arrow: { fontSize: 22, color: colors.textMuted },
  week: { flexDirection: "row" },
  weekday: { flex: 1, textAlign: "center", ...font.caption, color: colors.textMuted },
  cellBox: { flex: 1, alignItems: "center", paddingVertical: 1 },
  cell: { width: 40, height: 42, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  selected: { backgroundColor: colors.text },
  date: { fontSize: 15, color: colors.text },
  dateSelected: { color: colors.background, fontWeight: "700" },
  lunar: { fontSize: 9, lineHeight: 11, color: colors.accent, fontWeight: "700", letterSpacing: -0.2 },
  lunarSelected: { color: colors.surfaceStrong },
  save: {
    minHeight: 56,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.button,
    backgroundColor: colors.peach,
  },
  saveText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
