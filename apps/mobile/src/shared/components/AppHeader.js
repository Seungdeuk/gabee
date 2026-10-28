import { StyleSheet, View } from "react-native";

import { colors } from "@/theme";

import IconButton from "./IconButton";
import Logo from "./Logo";

/**
 * 채팅 화면 상단바: 왼쪽 메뉴, 가운데 로고, 오른쪽 새 대화와 더 보기.
 * menuBadge: 메뉴 버튼 위에 점을 띄운다(확인이 필요한 기록이 있을 때).
 * @param {{ onMenu?: () => void, onNew?: () => void, onMore?: () => void, menuBadge?: boolean }} props
 */
export default function AppHeader({ onMenu, onNew, onMore, menuBadge = false }) {
  return (
    <View style={styles.header}>
      <View>
        <IconButton name="menu-outline" label={menuBadge ? "메뉴, 확인이 필요한 기록이 있어요" : "메뉴"} onPress={onMenu} />
        {menuBadge ? <View style={styles.badge} pointerEvents="none" /> : null}
      </View>
      <Logo />
      <View style={styles.right}>
        <IconButton name="add" label="새 대화" onPress={onNew} />
        <IconButton name="settings-outline" size={22} label="설정" onPress={onMore} />
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
  badge: { position: "absolute", top: 9, right: 9, width: 9, height: 9, borderRadius: 5, backgroundColor: colors.peach, borderWidth: 1.5, borderColor: colors.background },
});
