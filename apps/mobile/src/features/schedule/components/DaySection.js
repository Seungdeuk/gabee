import { StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

import { compareItems } from "../model";
import EventCard from "./EventCard";

/**
 * 하루치 카드 목록. 머리줄에 날짜 이름("오늘", "내일 · 10월 22일")과 체크한 수/전체(예: 2/3)를 보이고,
 * 순서는 약속 먼저 → 할 일.
 * @param {{ label: string, items: import("../model").ScheduleItem[], onPressItem?: (id: string) => void, onToggleItem: (id: string) => void }} props
 */
export default function DaySection({ label, items, onPressItem, onToggleItem }) {
  const sorted = [...items].sort(compareItems);
  const done = sorted.filter((item) => item.checked).length;
  return (
    <View style={styles.section}>
      <View style={styles.head}>
        <Text style={styles.label}>{label}</Text>
        {sorted.length > 0 ? <Text style={styles.label}>{`${done}/${sorted.length}`}</Text> : null}
      </View>
      {sorted.length === 0 ? <Text style={styles.empty}>등록된 일정이 없어요</Text> : null}
      <View style={styles.rows}>
        {sorted.map((item) => (
          <EventCard
            key={item.id}
            item={item}
            onPress={onPressItem ? () => onPressItem(item.id) : undefined}
            onToggleCheck={() => onToggleItem(item.id)}
          />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { gap: 2 },
  head: { flexDirection: "row", justifyContent: "space-between" },
  label: { ...font.bodyStrong, fontWeight: "500", color: colors.textMuted },
  rows: { gap: spacing.sm },
  empty: { ...font.body, color: colors.textMuted },
});
