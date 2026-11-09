import { Ionicons } from "@expo/vector-icons";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import ReanimatedSwipeable from "react-native-gesture-handler/ReanimatedSwipeable";

import { colors, font, radius, spacing } from "@/theme";

import { muteActionLabel } from "../listUtils";
import RoomRow from "./RoomRow";

const LEAVE_LABEL = "나가기";
const ACTION_WIDTH = 88; // 종 아이콘+두 줄 라벨이 들어갈 고정 폭(theme 에 같은 크기의 토큰이 없다)

/**
 * 소통 탭 방 행. 왼쪽으로 밀면 오른쪽에 종 아이콘 액션("알림 끄기"/"알림 켜기")이 드러나고, 누르면 토글한 뒤 닫힌다.
 * 행을 누르면 기존처럼 방으로 이동한다(스와이프 중에는 눌림으로 치지 않는다). 웹이거나 onToggleMute 가 없으면 스와이프 없이 일반 행이고,
 * 스크린 리더는 RoomRow 의 접근성 액션으로 같은 토글을 쓴다.
 * @param {{ room: object, onPress?: () => void, onToggleMute?: () => void, divider?: boolean }} props room 은 RoomRow 의 room 과 같다(muted 포함)
 */
export default function SwipeableRoomRow({ room, onPress, onToggleMute, onLeave, divider = false }) {
  if (Platform.OS === "web" || !onToggleMute) return <RoomRow room={room} onPress={onPress} onToggleMute={onToggleMute} divider={divider} />;
  const label = muteActionLabel(room.muted === true);
  const canLeave = room.kind === "direct" && Boolean(onLeave); // 가족 전체방은 나갈 수 없다
  return (
    <ReanimatedSwipeable
      friction={2}
      overshootRight={false}
      rightThreshold={(canLeave ? ACTION_WIDTH * 2 : ACTION_WIDTH) / 2}
      renderRightActions={(_progress, _translation, methods) => (
        <View style={[styles.actionWrap, { width: canLeave ? ACTION_WIDTH * 2 : ACTION_WIDTH }]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={label}
            onPress={() => {
              methods.close();
              onToggleMute();
            }}
            style={({ pressed }) => [styles.action, pressed && styles.actionPressed]}
          >
            <Ionicons name={room.muted ? "notifications-outline" : "notifications-off-outline"} size={22} color={colors.text} />
            <Text style={styles.actionText}>{label}</Text>
          </Pressable>
          {canLeave ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={LEAVE_LABEL}
              onPress={() => {
                methods.close();
                onLeave();
              }}
              style={({ pressed }) => [styles.action, styles.leave, pressed && styles.leavePressed]}
            >
              <Ionicons name="exit-outline" size={22} color={colors.danger} />
              <Text style={[styles.actionText, styles.leaveText]}>{LEAVE_LABEL}</Text>
            </Pressable>
          ) : null}
        </View>
      )}
    >
      <View style={styles.front}>
        <RoomRow room={room} onPress={onPress} onToggleMute={onToggleMute} divider={divider} />
      </View>
    </ReanimatedSwipeable>
  );
}

const styles = StyleSheet.create({
  front: { backgroundColor: colors.background }, // 행 배경이 투명하면 뒤에 깔린 액션이 닫힌 상태에서도 비친다
  actionWrap: { width: ACTION_WIDTH, flexDirection: "row", gap: spacing.xs, paddingVertical: spacing.xs },
  action: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.xs, borderRadius: radius.lg, backgroundColor: colors.honeySoft },
  actionPressed: { backgroundColor: colors.surfaceStrong },
  actionText: { ...font.tab, color: colors.text },
  leave: { backgroundColor: colors.dangerSoft },
  leavePressed: { opacity: 0.7 },
  leaveText: { color: colors.danger },
});
