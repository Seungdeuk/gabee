import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, font, spacing } from "@/theme";

import { buildMarks, itemsOnDate } from "../calendar";
import EventCard from "../components/EventCard";
import FilterRows from "../components/FilterRows";
import MonthCalendar from "../components/MonthCalendar";
import SegmentedControl from "../components/SegmentedControl";
import { KIND } from "../constants";
import { applyFilter } from "../model";
import { toggleChecked, useScheduleItems } from "../store";
import { addDays, formatDateLong, shiftMonthKey, todayKey } from "../utils/date";

const VIEW_OPTIONS = [
  { key: "calendar", label: "달력" },
  { key: "list", label: "목록" },
];
const KIND_OPTIONS = [
  { key: "all", label: "모두" },
  { key: "appointment", label: "약속" },
  { key: "todo", label: "할 일" },
];

const toggle = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

/**
 * 달력 화면(달력 모드): 필터 칩 → 월 달력 → 선택한 날짜의 목록.
 * 목록 모드와 필터를 켜면 목록으로 자동 전환되는 동작은 다음 PR에서 붙인다.
 * 등록(+)·상세(카드 터치) 이동도 해당 화면을 만들 때 연결한다.
 */
export default function CalendarScreen() {
  const { date } = useLocalSearchParams();
  const items = useScheduleItems();
  const [selected, setSelected] = useState(/^\d{4}-\d{2}-\d{2}$/.test(date ?? "") ? date : todayKey());
  const [view, setView] = useState("calendar");
  const [kind, setKind] = useState("all");
  const [collapsed, setCollapsed] = useState(false);
  const [filter, setFilter] = useState({ whoIds: [], topicIds: [] });

  const filtered = applyFilter(items, filter);
  const dayItems = itemsOnDate(filtered, selected);
  const visible = kind === "all" ? dayItems : dayItems.filter((item) => item.kind === kind);
  const done = dayItems.filter((item) => item.checked).length;

  const shift = (delta) => setSelected(collapsed ? addDays(selected, delta * 7) : shiftMonthKey(selected, delta));

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <Text style={styles.title} accessibilityRole="header">
              한눈에 보는 한 달
            </Text>
            <SegmentedControl options={VIEW_OPTIONS} value={view} onChange={setView} />
          </View>

          <FilterRows
            filter={filter}
            onToggleWho={(id) => setFilter((f) => ({ ...f, whoIds: toggle(f.whoIds, id) }))}
            onToggleTopic={(id) => setFilter((f) => ({ ...f, topicIds: toggle(f.topicIds, id) }))}
          />

          {view === "calendar" ? (
            <>
              <MonthCalendar
                selected={selected}
                marks={buildMarks(filtered)}
                collapsed={collapsed}
                onSelect={setSelected}
                onShift={shift}
                onToggleCollapse={() => setCollapsed((c) => !c)}
              />
              <View style={styles.section}>
                <View style={styles.dayHead}>
                  <Text style={styles.dayTitle}>
                    {formatDateLong(selected)}
                    {dayItems.length > 0 ? <Text style={styles.dayCount}>{`  ${done}/${dayItems.length}`}</Text> : null}
                  </Text>
                  <Pressable style={styles.plus} accessibilityRole="button" accessibilityLabel="추가">
                    <Ionicons name="add" size={18} color={colors.text} />
                  </Pressable>
                </View>
                <SegmentedControl options={KIND_OPTIONS} value={kind} onChange={setKind} full />
                <View style={styles.rows}>
                  {visible.length === 0 ? (
                    <Text style={styles.empty}>
                      {kind === KIND.appointment ? "약속이 없어요" : kind === KIND.todo ? "할 일이 없어요" : "등록된 일정이 없어요"}
                    </Text>
                  ) : null}
                  {visible.map((item) => (
                    <EventCard key={item.id} item={item} variant="detailed" onToggleCheck={() => toggleChecked(item.id)} />
                  ))}
                </View>
              </View>
            </>
          ) : (
            <Text style={styles.empty}>목록 보기는 준비 중이에요</Text>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 14 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  title: { ...font.page, color: colors.text, flexShrink: 1 },
  section: { gap: spacing.md },
  dayHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dayTitle: { ...font.title, color: colors.text },
  dayCount: { ...font.bodyStrong, fontWeight: "500", color: colors.textMuted },
  plus: {
    width: 28,
    height: 28,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.peach,
  },
  rows: { gap: 10 },
  empty: { ...font.body, color: colors.textMuted },
});
