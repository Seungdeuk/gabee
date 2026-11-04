import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

/**
 * 공유 일정 목록 한 행. 행 전체가 터치 영역이다.
 * @param {{ item: { title: string, weekday: string, day: number, meta: string }, onPress: () => void }} props
 * @returns {import("react").ReactElement}
 */
function EventRow({ item, onPress }) {
  return (
    <Pressable
      style={styles.row}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${item.weekday}요일 ${item.day}일 ${item.title}, ${item.meta}`}
    >
      <View style={styles.date}>
        <Text style={styles.weekday}>{item.weekday}</Text>
        <Text style={styles.day}>{item.day}</Text>
      </View>
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={1}>
          {item.title}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {item.meta}
        </Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.placeholder} />
    </Pressable>
  );
}

/**
 * 공유 일정 목록: 제목 + 전체 건수, 행 사이 가는 선(카드 아님).
 * @param {{ title: string, total: number, list: object[], onPressItem: () => void }} props
 * @returns {import("react").ReactElement}
 */
export default function EventList({ title, total, list, onPressItem }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.heading}>{title}</Text>
        <Text style={styles.count}>{`${total}건`}</Text>
      </View>
      {list.map((item, index) => (
        <View key={item.id} style={index > 0 ? styles.divided : null}>
          <EventRow item={item} onPress={onPressItem} />
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  head: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  heading: { ...font.section, color: colors.text },
  count: { ...font.caption, color: colors.textMuted },
  divided: { borderTopWidth: 1, borderTopColor: colors.divider },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56, paddingVertical: spacing.sm },
  date: { width: 40, alignItems: "center" },
  weekday: { ...font.caption, color: colors.textMuted },
  day: { ...font.cardTitle, color: colors.text },
  body: { flex: 1, gap: spacing.xs },
  title: { ...font.bodyStrong, color: colors.text },
  meta: { ...font.caption, color: colors.textMuted },
});
