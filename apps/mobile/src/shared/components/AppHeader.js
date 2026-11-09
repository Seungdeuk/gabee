import { StyleSheet, View } from "react-native";

import { colors } from "@/theme";

import IconButton from "./IconButton";
import Logo from "./Logo";

/**
 * 채팅 화면 상단바: 왼쪽 메뉴, 가운데 로고, 오른쪽 새 대화(+)와 맨 오른쪽 알림 종. 바탕은 투명해서 화면 뒤 배경이 비친다.
 * menuBadge: 메뉴 버튼 위에 점을 띄운다(확인이 필요한 기록이 있을 때).
 * bell: 맨 오른쪽에 놓을 알림 종(라우트에서 조립해 넘긴다. 숫자 배지도 그 안에 있다).
 * @param {{ onMenu?: () => void, onNew?: () => void, menuBadge?: boolean, bell?: import("react").ReactNode }} props
 */
export default function AppHeader({ onMenu, onNew, menuBadge = false, bell = null }) {
  return (
    <View style={styles.header}>
      <View style={styles.side}>
        <View style={styles.menu}>
          <IconButton name="menu-outline" label={menuBadge ? "메뉴, 확인이 필요한 기록이 있어요" : "메뉴"} onPress={onMenu} />
          {menuBadge ? <View style={styles.badge} pointerEvents="none" /> : null}
        </View>
      </View>
      <Logo />
      <View style={[styles.side, styles.right]}>
        <IconButton name="add" label="새 대화" onPress={onNew} />
        {bell}
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
  },
  // 양쪽 영역을 같은 너비(flex 1)로 두어, 오른쪽 버튼 수와 상관없이 로고가 화면 가운데에 온다
  side: { flex: 1 },
  menu: { alignSelf: "flex-start" }, // 메뉴 점 배지가 버튼 모서리에 붙도록 버튼 크기만큼만 차지한다
  right: {
    flexDirection: "row",
    justifyContent: "flex-end",
  },
  badge: { position: "absolute", top: 9, right: 9, width: 9, height: 9, borderRadius: 5, backgroundColor: colors.peach, borderWidth: 1.5, borderColor: colors.background },
});
