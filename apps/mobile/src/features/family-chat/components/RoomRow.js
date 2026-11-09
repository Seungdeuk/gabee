import { Ionicons } from "@expo/vector-icons";
import { PixelRatio, Pressable, StyleSheet, Text, View } from "react-native";

import HexAvatar from "@/shared/components/HexAvatar";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, radius, spacing } from "@/theme";

import { muteActionLabel, roomA11yLabel, unreadBadgeText } from "../listUtils";

const MUTE_ACTION = "mute";

/**
 * 채팅방 한 줄(메신저 목록 모양): 큰 원형 프로필, 방 이름+구성원 수, 마지막 말 한 줄, 오른쪽 위 시각.
 * 안 읽은 메시지가 있으면 오른쪽 아래에 복숭아색 원 배지(99 넘으면 "99+")를 보이고 마지막 말을 굵게 한다.
 * 1:1 방(peerId 가 있음)은 상대의 프로필 사진/이니셜(옅은 테두리 원형), 가족 전체방은 육각형 가족 아바타를 보인다.
 * 알림을 끈 방(muted)은 방 이름(구성원 수) 오른쪽에 알림 꺼짐 아이콘을 보이되 안 읽은 숫자 배지는 그대로 둔다.
 * divider 가 true 면 행 아래에 사진 오른쪽부터 시작하는 얇은 구분선을 그린다(마지막 행은 false).
 * onToggleMute 가 있으면 스크린 리더용 접근성 액션("알림 끄기"/"알림 켜기")을 함께 제공한다(스와이프를 못 쓰는 환경의 대체).
 * @param {{ room: { name: string, last: string, time: string, tone?: string, count?: number, unread?: number, muted?: boolean, peerId?: string, photoUrl?: string | null, a11yTitle?: string }, onPress?: () => void, onToggleMute?: () => void, divider?: boolean }} props
 */
export default function RoomRow({ room, onPress, onToggleMute, divider = false }) {
  const unread = room.unread ?? 0;
  const badge = unreadBadgeText(unread);
  return (
    <View>
      <Pressable
        onPress={onPress}
        disabled={!onPress}
        accessibilityRole={onPress ? "button" : undefined}
        accessibilityLabel={roomA11yLabel(room.last, unread, room.a11yTitle)}
        accessibilityActions={onToggleMute ? [{ name: MUTE_ACTION, label: muteActionLabel(room.muted === true) }] : undefined}
        onAccessibilityAction={onToggleMute ? (event) => event.nativeEvent.actionName === MUTE_ACTION && onToggleMute() : undefined}
        style={({ pressed }) => [styles.row, pressed && styles.pressed]}
      >
        {room.peerId ? (
          <View style={styles.ring}>
            <UserAvatar name={room.name} userId={room.peerId} photoUrl={room.photoUrl} size={AVATAR_SIZE - RING_SPACE} />
          </View>
        ) : (
          <HexAvatar name={room.name} size={AVATAR_SIZE} />
        )}
        <View style={styles.main}>
          <View style={styles.titleLine}>
            <Text style={styles.name} numberOfLines={1}>
              {room.name}
            </Text>
            {room.count ? <Text style={styles.count}>{room.count}</Text> : null}
            {room.muted ? <Ionicons name="notifications-off-outline" size={16} color={colors.textMuted} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" /> : null}
          </View>
          <Text style={[styles.last, unread > 0 && styles.lastUnread]} numberOfLines={1}>
            {room.last}
          </Text>
        </View>
        <View style={styles.side}>
          <View style={styles.timeLine}>
            <Text style={styles.time}>{room.time}</Text>
          </View>
          {badge ? (
            <View style={styles.badge}>
              <Text style={styles.badgeText}>{badge}</Text>
            </View>
          ) : null}
        </View>
      </Pressable>
      {divider ? <View style={styles.divider} /> : null}
    </View>
  );
}

const BADGE_SIZE = 22;
const AVATAR_SIZE = 56;
const RING_BORDER = 2; // 1:1 프로필을 둘러싼 옅은 테두리 두께
const RING_SPACE = RING_BORDER * 4; // 테두리 두 겹(바깥 테두리 + 안쪽 여백)이 차지하는 폭: 전체 크기는 그대로 56
const DIVIDER_HEIGHT = 1 / PixelRatio.get(); // 정확히 물리 픽셀 1개: 1dp 는 화면 밀도에 따라 2~3픽셀로 갈려 행마다 굵기가 달라 보이고, 2픽셀은 줄여 본 화면에서 줄 사이에 걸리면 두꺼워 보인다

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
  ring: { width: AVATAR_SIZE, height: AVATAR_SIZE, padding: RING_BORDER, borderWidth: RING_BORDER, borderColor: colors.peachSoft, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  divider: { height: DIVIDER_HEIGHT, marginLeft: spacing.sm + AVATAR_SIZE + spacing.md, backgroundColor: colors.disabled },
  main: { flex: 1, minWidth: 0, gap: spacing.xs, paddingTop: spacing.xs },
  titleLine: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  name: { ...font.cardTitle, color: colors.text, flexShrink: 1 },
  count: { ...font.caption, color: colors.textMuted },
  last: { ...font.caption, color: colors.textSub },
  lastUnread: { fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  side: { alignSelf: "stretch", alignItems: "flex-end", justifyContent: "space-between", gap: spacing.xs },
  timeLine: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingTop: spacing.xs },
  time: { ...font.caption, color: colors.textMuted },
  // 배지 크기 22 는 theme 에 맞는 토큰이 없어(spacing 최대 24·최소 20 사이) 숫자로 둔다. 가로 여백은 spacing.xs 토큰 사용
  badge: { minWidth: BADGE_SIZE, height: BADGE_SIZE, paddingHorizontal: spacing.xs, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.peach },
  badgeText: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
});
