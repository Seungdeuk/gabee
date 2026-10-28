import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import IconButton from "./IconButton";
import Logo from "./Logo";

/**
 * 채팅 화면 상단바: 왼쪽 메뉴, 가운데 로고, 오른쪽 새 대화와 더 보기.
 * menuBadge: 메뉴 버튼 위에 점을 띄운다(확인이 필요한 기록이 있을 때).
 * onBell 를 주면 오른쪽에 알림 종 아이콘이 붙고, bellBadge(예: "3", "99+")가 있으면 종 위에 숫자 배지를 띄운다.
 * @param {{ onMenu?: () => void, onNew?: () => void, onMore?: () => void, menuBadge?: boolean, onBell?: () => void, bellBadge?: string | null }} props
 */
export default function AppHeader({ onMenu, onNew, onMore, menuBadge = false, onBell, bellBadge = null }) {
  return (
    <View style={styles.header}>
      <View>
        <IconButton name="menu-outline" label={menuBadge ? "메뉴, 확인이 필요한 기록이 있어요" : "메뉴"} onPress={onMenu} />
        {menuBadge ? <View style={styles.badge} pointerEvents="none" /> : null}
      </View>
      <Logo />
      <View style={styles.right}>
        {onBell ? (
          <View>
            <IconButton name="notifications-outline" label={bellBadge ? `알림, 안 읽은 알림 ${bellBadge}개` : "알림"} onPress={onBell} />
            {bellBadge ? (
              <View style={styles.count} pointerEvents="none">
                <Text style={styles.countText}>{bellBadge}</Text>
              </View>
            ) : null}
          </View>
        ) : null}
        <IconButton name="add" label="새 대화" onPress={onNew} />
        <IconButton name="ellipsis-vertical" size={20} label="설정" onPress={onMore} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    height: 56,
    paddingHorizontal: 6,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.background,
  },
  right: {
    flexDirection: "row",
  },
  count: { position: "absolute", top: 4, right: 2, minWidth: 18, height: 18, paddingHorizontal: 4, borderRadius: 9, alignItems: "center", justifyContent: "center", backgroundColor: colors.peach, borderWidth: 1.5, borderColor: colors.background },
  countText: { ...font.tab, color: colors.text }, // 글자 크기는 theme 토큰만 쓴다
  badge: { position: "absolute", top: 9, right: 9, width: 9, height: 9, borderRadius: 5, backgroundColor: colors.peach, borderWidth: 1.5, borderColor: colors.background },
});
