import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Tag from "@/shared/components/Tag";
import { colors, font, radius, spacing } from "@/theme";

import { relativeTime } from "../format";
import { metaFor } from "../kinds";

/**
 * 알림 한 줄: 분류 아이콘(분류 색)과 분류 이름 태그, 제목·내용·시각. 안 읽은 알림은 제목이 굵고 점이 붙는다.
 * @param {{ item: { id: string, kind: string, title: string, body?: string | null, created_at: string, read_at: string | null }, onPress: () => void }} props
 */
export default function NotificationRow({ item, onPress }) {
  const meta = metaFor(item.kind);
  const unread = !item.read_at;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${meta.label} 알림, ${item.title}${unread ? ", 안 읽음" : ""}`}
      style={({ pressed }) => [styles.row, unread && styles.unreadRow, pressed && styles.pressed]}
      testID={`notification-${item.id}`}
    >
      <View style={[styles.icon, { backgroundColor: colors.card, borderColor: meta.color }]}>
        <Ionicons name={meta.icon} size={20} color={meta.color} />
      </View>
      <View style={styles.text}>
        <View style={styles.head}>
          <Tag label={meta.label} />
          <Text style={styles.time}>{relativeTime(item.created_at)}</Text>
        </View>
        <Text style={[styles.title, unread && styles.titleUnread]}>{item.title}</Text>
        {item.body ? <Text style={styles.body}>{item.body}</Text> : null}
      </View>
      {unread ? <View style={styles.dot} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.card,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  unreadRow: { backgroundColor: colors.peachSoft, borderColor: colors.border },
  pressed: { opacity: 0.85 },
  icon: { width: 40, height: 40, borderRadius: 20, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  text: { flex: 1, gap: 2 },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  time: { ...font.caption, color: colors.textMuted },
  title: { ...font.body, color: colors.text },
  titleUnread: { ...font.bodyStrong },
  body: { ...font.caption, color: colors.textSub },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.peach },
});
