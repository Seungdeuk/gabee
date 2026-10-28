import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

import { compareItems } from "../model";
import EventCard from "./EventCard";

/**
 * 하루치 카드 목록. 머리줄에 날짜 이름("오늘", "내일 · 10월 22일")과 체크한 수/전체(예: 2/3)를 보이고,
 * 순서는 약속 먼저 → 할 일. onToggle 이 있으면 날짜 이름을 눌러 접고 펼 수 있다(접어도 개수는 보인다).
 * @param {{ label: string, items: import("../model").ScheduleItem[], onPressItem?: (id: string) => void, onToggleItem: (id: string) => void,
 *   collapsed?: boolean, onToggle?: () => void }} props
 */
export default function DaySection({ label, items, onPressItem, onToggleItem, collapsed = false, onToggle }) {
  const sorted = [...items].sort(compareItems);
  const done = sorted.filter((item) => item.checked).length;
  const arrow = onToggle ? (collapsed ? " ▸" : " ▾") : "";
  return (
    <View style={styles.section}>
      <View style={styles.head}>
        <Pressable onPress={onToggle} disabled={!onToggle} hitSlop={8} accessibilityRole="button" accessibilityState={{ expanded: !collapsed }}>
          <Text style={styles.label}>{`${label}${arrow}`}</Text>
        </Pressable>
        {sorted.length > 0 ? <Text style={styles.label}>{`${done}/${sorted.length}`}</Text> : null}
      </View>
      {collapsed ? null : (
        <>
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
        </>
      )}
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
