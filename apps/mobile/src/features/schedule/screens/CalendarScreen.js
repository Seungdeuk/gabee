import { useLocalSearchParams, useRouter } from "expo-router";
import { useRef, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import { buildMarks, itemsOnDate } from "../calendar";
import AddButton from "../components/AddButton";
import EventCard from "../components/EventCard";
import FilterRows from "../components/FilterRows";
import ListMode from "../components/ListMode";
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

/** 달력을 자동으로 접는 스크롤 위치(px)와, 접어도 스크롤이 남을 만큼 긴 내용인지 보는 여유(px). */
const AUTO_COLLAPSE_Y = 80;
const AUTO_COLLAPSE_SLACK = 400;

const toggle = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
const hasFilter = (filter) => filter.whoIds.length > 0 || filter.topicIds.length > 0;

/**
 * 달력 화면: [달력 | 목록] 두 가지 보기.
 * - 필터(누구·주제)를 하나라도 켜면 자동으로 목록, 모두 해제하면 달력으로 돌아온다. 버튼으로 직접 바꿀 수도 있다.
 * - 달력 모드에서 목록을 아래로 스크롤하면 달력이 접히고, 맨 위로 오면 다시 펴진다.
 * 날짜 옆 +와 목록의 오늘 옆 +는 등록 화면으로, 카드를 누르면 상세로 간다.
 */
export default function CalendarScreen() {
  const router = useRouter();
  const { date } = useLocalSearchParams();
  const items = useScheduleItems();
  const [selected, setSelected] = useState(/^\d{4}-\d{2}-\d{2}$/.test(date ?? "") ? date : todayKey());
  const [view, setView] = useState("calendar");
  const [kind, setKind] = useState("all");
  const [collapsed, setCollapsed] = useState(false);
  const [filter, setFilter] = useState({ whoIds: [], topicIds: [] });
  const scroll = useRef({ content: 0, viewport: 0, auto: false });
  const today = todayKey();

  const filtered = applyFilter(items, filter);
  const byKind = (list) => (kind === "all" ? list : list.filter((item) => item.kind === kind));
  const dayItems = itemsOnDate(filtered, selected);
  const visible = byKind(dayItems);
  const done = dayItems.filter((item) => item.checked).length;

  const changeFilter = (next) => {
    setFilter(next);
    setView(hasFilter(next) ? "list" : "calendar");
  };
  // 일정 메인으로 돌아간다. 주소를 직접 열어 쌓인 화면이 없어도 같은 곳으로 간다.
  const goBack = () => router.dismissTo("/(tabs)/schedule");
  // 그 날짜가 미리 채워진 등록 화면을 연다. 저장하면 이 화면으로 돌아온다.
  const openDetail = (id) => router.push({ pathname: "/schedule/detail", params: { id } });
  // 약속·할 일 필터가 켜져 있으면 그 형태로 열린다(모두면 기본 약속).
  const openRegister = (dateKey) =>
    router.push({ pathname: "/schedule/register", params: { date: dateKey, ...(kind === "all" ? {} : { kind }) } });
  const shift = (delta) => setSelected(collapsed ? addDays(selected, delta * 7) : shiftMonthKey(selected, delta));
  const toggleCollapse = () => {
    scroll.current.auto = false;
    setCollapsed((c) => !c);
  };
  const handleScroll = (event) => {
    if (view !== "calendar") return;
    const y = event.nativeEvent.contentOffset.y;
    const { content, viewport } = scroll.current;
    if (!collapsed && y > AUTO_COLLAPSE_Y && content > viewport + AUTO_COLLAPSE_SLACK) {
      scroll.current.auto = true;
      setCollapsed(true);
    } else if (collapsed && scroll.current.auto && y <= 0) {
      scroll.current.auto = false;
      setCollapsed(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        scrollEventThrottle={16}
        onScroll={handleScroll}
        onLayout={(e) => (scroll.current.viewport = e.nativeEvent.layout.height)}
        onContentSizeChange={(_, height) => (scroll.current.content = height)}
      >
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.titleBox}>
              <IconButton name="chevron-back" label="뒤로" onPress={goBack} />
              <Text style={styles.title} accessibilityRole="header">
                한눈에 보는 한 달
              </Text>
            </View>
            <SegmentedControl options={VIEW_OPTIONS} value={view} onChange={setView} />
          </View>

          <FilterRows
            filter={filter}
            onToggleWho={(id) => changeFilter({ ...filter, whoIds: toggle(filter.whoIds, id) })}
            onToggleTopic={(id) => changeFilter({ ...filter, topicIds: toggle(filter.topicIds, id) })}
          />

          {view === "calendar" ? (
            <>
              <MonthCalendar
                selected={selected}
                marks={buildMarks(filtered)}
                collapsed={collapsed}
                onSelect={setSelected}
                onShift={shift}
                onToggleCollapse={toggleCollapse}
              />
              <View style={styles.section}>
                <View style={styles.dayHead}>
                  <Text style={styles.dayTitle}>
                    {formatDateLong(selected)}
                    {dayItems.length > 0 ? <Text style={styles.dayCount}>{`  ${done}/${dayItems.length}`}</Text> : null}
                  </Text>
                  <AddButton label="추가" onPress={() => openRegister(selected)} />
                </View>
                <SegmentedControl options={KIND_OPTIONS} value={kind} onChange={setKind} full />
                <View style={styles.rows}>
                  {visible.length === 0 ? (
                    <Text style={styles.empty}>
                      {kind === KIND.appointment ? "약속이 없어요" : kind === KIND.todo ? "할 일이 없어요" : "등록된 일정이 없어요"}
                    </Text>
                  ) : null}
                  {visible.map((item) => (
                    <EventCard
                      key={item.id}
                      item={item}
                      variant="detailed"
                      onPress={() => openDetail(item.id)}
                      onToggleCheck={() => toggleChecked(item.id)}
                    />
                  ))}
                </View>
              </View>
            </>
          ) : (
            <>
              <View style={styles.listHead}>
                <Text style={styles.dayTitle}>{formatDateLong(today)}</Text>
                <SegmentedControl options={KIND_OPTIONS} value={kind} onChange={setKind} full />
              </View>
              <ListMode
                items={byKind(filtered)}
                today={today}
                onToggleItem={toggleChecked}
                onPressItem={openDetail}
                onAddToday={() => openRegister(today)}
              />
            </>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 7 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  titleBox: { flexDirection: "row", alignItems: "center", flexShrink: 1, marginLeft: -spacing.sm },
  title: { ...font.page, color: colors.text, flexShrink: 1 },
  section: { gap: 2 },
  listHead: { gap: 4 },
  dayHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dayTitle: { ...font.title, color: colors.text },
  dayCount: { ...font.bodyStrong, fontWeight: "500", color: colors.textMuted },
  rows: { gap: 10, marginTop: 3 },
  empty: { ...font.body, color: colors.textMuted },
});
