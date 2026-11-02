import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import IconButton from "./IconButton";
import Logo from "./Logo";

/**
 * 채팅 화면 상단바: 왼쪽 메뉴, 가운데 로고, 오른쪽 알림과 새 대화. 바탕은 투명해서 화면 뒤 배경이 비친다.
 * menuBadge: 메뉴 버튼 위에 점을 띄운다(확인이 필요한 기록이 있을 때).
 * onBell 를 주면 오른쪽에 알림 종 아이콘이 붙고, bellBadge(예: "3", "99+")가 있으면 종 위에 숫자 배지를 띄운다.
 * @param {{ onMenu?: () => void, onNew?: () => void, menuBadge?: boolean, onBell?: () => void, bellBadge?: string | null }} props
 */
export default function AppHeader({ onMenu, onNew, menuBadge = false, onBell, bellBadge = null }) {
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
  count: { position: "absolute", top: 0, right: -4, minWidth: 20, height: 20, paddingHorizontal: 5, borderRadius: 10, alignItems: "center", justifyContent: "center", backgroundColor: colors.peach, borderWidth: 1.5, borderColor: colors.background },
  countText: { ...font.caption, lineHeight: 15, includeFontPadding: false, textAlignVertical: "center", color: colors.text }, // 글자 크기는 theme 토큰만 쓴다. 줄 높이를 배지 안쪽 높이에 맞춰 숫자가 잘리지 않게 한다
  badge: { position: "absolute", top: 9, right: 9, width: 9, height: 9, borderRadius: 5, backgroundColor: colors.peach, borderWidth: 1.5, borderColor: colors.background },
});
