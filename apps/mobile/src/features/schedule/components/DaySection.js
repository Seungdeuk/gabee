import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

import { compareItems } from "../model";
import { mergeBriefing } from "../request_view";
import EventCard from "./EventCard";
import RequestCard from "./RequestCard";

/**
 * 하루치 카드 목록. 머리줄에 날짜 이름("오늘", "내일 · 10월 22일")과 체크한 수/전체(예: 2/3)를 보이고,
 * 순서는 약속 먼저 → 할 일. 내가 보낸 부탁(requests)은 약속 자리에 시간순으로 끼며 체크 수/전체에는 세지 않는다. onToggle 이 있으면 날짜 이름을 눌러 접고 펼 수 있다(접어도 개수는 보인다).
 * @param {{ label: string, items: import("../model").ScheduleItem[], requests?: import("../model").TogetherRequest[], onPressItem?: (id: string) => void,
 *   onPressRequest?: (id: string) => void, onToggleItem: (id: string) => void, collapsed?: boolean, onToggle?: () => void }} props
 */
export default function DaySection({ label, items, requests = [], onPressItem, onPressRequest, onToggleItem, collapsed = false, onToggle }) {
  const entries = mergeBriefing(items, requests, compareItems);
  const done = items.filter((item) => item.checked).length;
  const arrow = onToggle ? (collapsed ? " ▸" : " ▾") : "";
  return (
    <View style={styles.section}>
      <View style={styles.head}>
        <Pressable onPress={onToggle} disabled={!onToggle} hitSlop={8} accessibilityRole="button" accessibilityState={{ expanded: !collapsed }}>
          <Text style={styles.label}>{`${label}${arrow}`}</Text>
        </Pressable>
        {items.length > 0 ? <Text style={styles.label}>{`${done}/${items.length}`}</Text> : null}
      </View>
      {collapsed ? null : (
        <>
          {entries.length === 0 ? <Text style={styles.empty}>등록된 일정이 없어요</Text> : null}
          <View style={styles.rows}>
            {entries.map((entry) =>
              entry.type === "request" ? (
                <RequestCard
                  key={`request-${entry.request.id}`}
                  request={entry.request}
                  onPress={onPressRequest ? () => onPressRequest(entry.request.id) : undefined}
                />
              ) : (
                <EventCard
                  key={entry.item.id}
                  item={entry.item}
                  onPress={onPressItem ? () => onPressItem(entry.item.id) : undefined}
                  onToggleCheck={() => onToggleItem(entry.item.id)}
                />
              ),
            )}
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
