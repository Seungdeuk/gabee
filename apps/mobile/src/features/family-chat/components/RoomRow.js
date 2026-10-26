import { Pressable, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, radius, spacing } from "@/theme";

import { roomA11yLabel, unreadBadgeText } from "../listUtils";

/**
 * 채팅방 한 줄(메신저 목록 모양): 큰 원형 프로필, 방 이름+구성원 수, 마지막 말 한 줄, 오른쪽 위 시각.
 * 안 읽은 메시지가 있으면 오른쪽 아래에 복숭아색 원 배지(99 넘으면 "99+")를 보이고 마지막 말을 굵게 한다.
 * 1:1 방(peerId 가 있음)은 상대의 프로필 사진/이니셜, 가족 전체방은 가족 아바타를 보인다.
 * @param {{ room: { name: string, last: string, time: string, tone?: string, count?: number, unread?: number, peerId?: string, photoUrl?: string | null, a11yTitle?: string }, onPress?: () => void }} props
 */
export default function RoomRow({ room, onPress }) {
  const unread = room.unread ?? 0;
  const badge = unreadBadgeText(unread);
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? "button" : undefined}
      accessibilityLabel={roomA11yLabel(room.last, unread, room.a11yTitle)}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      {room.peerId ? <UserAvatar name={room.name} userId={room.peerId} photoUrl={room.photoUrl} size={56} /> : <Avatar name={room.name} tone={room.tone} size={56} />}
      <View style={styles.main}>
        <View style={styles.titleLine}>
          <Text style={styles.name} numberOfLines={1}>
            {room.name}
          </Text>
          {room.count ? <Text style={styles.count}>{room.count}</Text> : null}
        </View>
        <Text style={[styles.last, unread > 0 && styles.lastUnread]} numberOfLines={1}>
          {room.last}
        </Text>
      </View>
      <View style={styles.side}>
        <Text style={styles.time}>{room.time}</Text>
        {badge ? (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{badge}</Text>
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

const BADGE_SIZE = 22;

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
  titleLine: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  name: { ...font.cardTitle, color: colors.text, flexShrink: 1 },
  count: { ...font.caption, color: colors.textMuted },
  last: { ...font.caption, color: colors.textSub },
  lastUnread: { fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  side: { alignSelf: "stretch", alignItems: "flex-end", justifyContent: "space-between", gap: spacing.xs },
  time: { ...font.caption, color: colors.textMuted, paddingTop: spacing.xs },
  // 배지 크기 22 는 theme 에 맞는 토큰이 없어(spacing 최대 24·최소 20 사이) 숫자로 둔다. 가로 여백은 spacing.xs 토큰 사용
  badge: { minWidth: BADGE_SIZE, height: BADGE_SIZE, paddingHorizontal: spacing.xs, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.peach },
  badgeText: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
});
