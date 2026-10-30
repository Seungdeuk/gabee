import { Ionicons } from "@expo/vector-icons";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import ReanimatedSwipeable from "react-native-gesture-handler/ReanimatedSwipeable";

import { colors, font, radius, spacing } from "@/theme";

import { muteActionLabel } from "../listUtils";
import RoomRow from "./RoomRow";

const ACTION_WIDTH = 88; // 종 아이콘+두 줄 라벨이 들어갈 고정 폭(theme 에 같은 크기의 토큰이 없다)

/**
 * 소통 탭 방 행. 왼쪽으로 밀면 오른쪽에 종 아이콘 액션("알림 끄기"/"알림 켜기")이 드러나고, 누르면 토글한 뒤 닫힌다.
 * 행을 누르면 기존처럼 방으로 이동한다(스와이프 중에는 눌림으로 치지 않는다). 웹이거나 onToggleMute 가 없으면 스와이프 없이 일반 행이고,
 * 스크린 리더는 RoomRow 의 접근성 액션으로 같은 토글을 쓴다.
 * @param {{ room: object, onPress?: () => void, onToggleMute?: () => void }} props room 은 RoomRow 의 room 과 같다(muted 포함)
 */
export default function SwipeableRoomRow({ room, onPress, onToggleMute }) {
  if (Platform.OS === "web" || !onToggleMute) return <RoomRow room={room} onPress={onPress} onToggleMute={onToggleMute} />;
  const label = muteActionLabel(room.muted === true);
  return (
    <ReanimatedSwipeable
      friction={2}
      overshootRight={false}
      rightThreshold={ACTION_WIDTH / 2}
      renderRightActions={(_progress, _translation, methods) => (
        <View style={styles.actionWrap}>
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
        </View>
      )}
    >
      <RoomRow room={room} onPress={onPress} onToggleMute={onToggleMute} />
    </ReanimatedSwipeable>
  );
}

const styles = StyleSheet.create({
  actionWrap: { width: ACTION_WIDTH, justifyContent: "center", paddingVertical: spacing.xs },
  action: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.xs, borderRadius: radius.lg, backgroundColor: colors.honeySoft },
  actionPressed: { backgroundColor: colors.surfaceStrong },
  actionText: { ...font.tab, color: colors.text },
});
