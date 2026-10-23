import { Pressable, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import { colors, font, radius, spacing } from "@/theme";

import { roomA11yLabel } from "../listUtils";

/**
 * 채팅방 한 줄(메신저 목록 모양): 큰 원형 프로필, 방 이름+구성원 수, 마지막 말 한 줄, 오른쪽 위 시각.
 * 읽지 않은 수는 서버가 없어 보여주지 않는다.
 * @param {{ room: { name: string, last: string, time: string, tone: string, count?: number }, onPress?: () => void }} props
 */
export default function RoomRow({ room, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? "button" : undefined}
      accessibilityLabel={roomA11yLabel(room.last)}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <Avatar name={room.name} tone={room.tone} size={56} />
      <View style={styles.main}>
        <View style={styles.titleLine}>
          <Text style={styles.name} numberOfLines={1}>
            {room.name}
          </Text>
          {room.count ? <Text style={styles.count}>{room.count}</Text> : null}
        </View>
        <Text style={styles.last} numberOfLines={1}>
          {room.last}
        </Text>
      </View>
      <Text style={styles.time}>{room.time}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 72,
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.lg,
  },
  pressed: { backgroundColor: colors.surface },
  main: { flex: 1, minWidth: 0, gap: spacing.xs, paddingTop: spacing.xs },
  titleLine: { flexDirection: "row", alignItems: "center", gap: 6 },
  name: { ...font.cardTitle, color: colors.text, flexShrink: 1 },
  count: { ...font.caption, color: colors.textMuted },
  last: { ...font.caption, color: colors.textSub },
  time: { ...font.caption, color: colors.textMuted, paddingTop: spacing.xs },
});
