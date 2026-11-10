import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import { colors, font } from "@/theme";

import { badgeLabel } from "../format";
import useUnread from "../useUnread";

/**
 * 모든 탭 화면 오른쪽 위에 같은 모양·같은 자리로 붙는 알림 종. 누르면 알림함으로 가고, 안 읽은 알림이 있으면 숫자 배지(예: "3", "99+")를 띄운다.
 * 각 탭 라우트가 이 컴포넌트를 화면에 넘겨 조립한다(기능끼리 서로 import 하지 않게).
 * @returns {import("react").ReactElement}
 */
export default function TabBell() {
  const router = useRouter();
  const { total } = useUnread();
  const badge = badgeLabel(total);
  return (
    <View>
      <IconButton name="notifications-outline" label={badge ? `알림, 안 읽은 알림 ${badge}개` : "알림"} onPress={() => router.push("/notifications")} />
      {badge ? (
        <View style={styles.count} pointerEvents="none">
          <Text style={styles.countText}>{badge}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  count: { position: "absolute", top: 0, right: -4, minWidth: 20, height: 20, paddingHorizontal: 5, borderRadius: 10, alignItems: "center", justifyContent: "center", backgroundColor: colors.peach, borderWidth: 1.5, borderColor: colors.background },
  countText: { ...font.caption, lineHeight: 15, includeFontPadding: false, textAlignVertical: "center", color: colors.text }, // 글자 크기는 theme 토큰만 쓴다. 줄 높이를 배지 안쪽 높이에 맞춰 숫자가 잘리지 않게 한다
});
