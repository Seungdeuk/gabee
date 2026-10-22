import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { groupByMonth, splitByTime } from "../calendar";
import { DOT_COLOR, WEEKDAYS } from "../constants";
import { fromDateKey } from "../utils/date";
import AddButton from "./AddButton";
import EventCard from "./EventCard";
import SectionHeader from "./SectionHeader";

/** 지난 것을 펼쳤을 때 먼저 보이는 개수. 나머지는 "이전 기록 N개 더 보기". */
const PAST_PREVIEW = 3;

const countOf = (items) => `${items.filter((item) => item.checked).length}/${items.length}`;

/**
 * 목록 모드: 오늘 → 다가오는 것(월 구분선) → 지난 것. 구역 제목을 누르면 각각 접고 편다.
 * 오늘은 비어 있어도 항상 보이고, 지난 것은 기본 접힘이며 없으면 숨긴다.
 * @param {{ items: import("../model").ScheduleItem[], today: string, onToggleItem: (id: string) => void, onAddToday?: () => void }} props
 */
export default function ListMode({ items, today, onToggleItem, onAddToday }) {
  const [fold, setFold] = useState({ today: false, upcoming: false, past: true });
  const [morePast, setMorePast] = useState(false);
  const toggleFold = (key) => setFold((f) => ({ ...f, [key]: !f[key] }));
  const parts = splitByTime(items, today);
  const pastShown = morePast ? parts.past : parts.past.slice(0, PAST_PREVIEW);

  return (
    <View style={styles.wrap}>
      <View style={styles.section}>
        <SectionHeader
          title="오늘"
          count={parts.today.length > 0 ? countOf(parts.today) : undefined}
          collapsed={fold.today}
          onToggle={() => toggleFold("today")}
          right={<AddButton label="오늘 추가" onPress={onAddToday} />}
        />
        {fold.today ? null : parts.today.length === 0 ? (
          <Text style={styles.empty}>오늘은 등록된 일정이 없어요</Text>
        ) : (
          <Rows items={parts.today} today={today} onToggleItem={onToggleItem} />
        )}
      </View>

      {parts.upcoming.length > 0 ? (
        <View style={styles.section}>
          <SectionHeader
            title="다가오는 것"
            collapsed={fold.upcoming}
            onToggle={() => toggleFold("upcoming")}
          />
          {fold.upcoming
            ? null
            : groupByMonth(parts.upcoming).map((group) => (
                <View key={group.key} style={styles.section}>
                  <Text style={styles.month}>{group.label}</Text>
                  <Rows items={group.items} today={today} onToggleItem={onToggleItem} />
                </View>
              ))}
        </View>
      ) : null}

      {parts.past.length > 0 ? (
        <View style={styles.section}>
          <SectionHeader title="지난 것" collapsed={fold.past} onToggle={() => toggleFold("past")} />
          {fold.past ? null : (
            <>
              <Rows items={pastShown} today={today} past />
              {!morePast && parts.past.length > PAST_PREVIEW ? (
                <Pressable onPress={() => setMorePast(true)} style={styles.more} accessibilityRole="button">
                  <Text style={styles.moreText}>이전 기록 {parts.past.length - PAST_PREVIEW}개 더 보기</Text>
                </Pressable>
              ) : null}
            </>
          )}
        </View>
      ) : null}
    </View>
  );
}

/** 날짜 열(일 + 요일 또는 "오늘") + 카드. 같은 날짜가 이어지면 날짜는 첫 줄에만 보인다. */
function Rows({ items, today, past = false, onToggleItem }) {
  return (
    <View style={styles.rows}>
      {items.map((item, index) => {
        const first = index === 0 || items[index - 1].date !== item.date;
        const day = fromDateKey(item.date);
        const isToday = item.date === today;
        return (
          <View key={item.id} style={styles.row}>
            <View style={styles.dateCol}>
              {first ? (
                <>
                  <Text style={[styles.dateNum, past && styles.dim]}>{day.getDate()}</Text>
                  <Text style={[styles.dateLabel, isToday && styles.todayLabel]}>
                    {isToday ? "오늘" : WEEKDAYS[day.getDay()]}
                  </Text>
                </>
              ) : null}
            </View>
            <View style={styles.card}>
              <EventCard
                item={item}
                variant="detailed"
                past={past}
                onToggleCheck={onToggleItem ? () => onToggleItem(item.id) : undefined}
              />
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xl },
  section: { gap: spacing.md },
  rows: { gap: spacing.md },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  dateCol: { width: 44, alignItems: "center" },
  dateNum: { ...font.title, color: colors.text },
  dim: { color: colors.textMuted },
  dateLabel: { fontSize: 13, color: colors.textMuted },
  todayLabel: { color: DOT_COLOR, fontWeight: "700" },
  card: { flex: 1 },
  month: { ...font.bodyStrong, fontWeight: "500", color: colors.textMuted, marginTop: 4 },
  empty: { ...font.body, color: colors.textMuted },
  more: {
    alignItems: "center",
    paddingVertical: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.button,
  },
  moreText: { fontSize: 14, fontWeight: "500", color: colors.textMuted },
});
