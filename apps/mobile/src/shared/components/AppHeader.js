import { StyleSheet, View } from "react-native";

import { colors } from "@/theme";

import IconButton from "./IconButton";
import Logo from "./Logo";

/**
 * 채팅 화면 상단바: 왼쪽 메뉴, 가운데 로고, 오른쪽 새 대화와 더 보기.
 * @param {{ onMenu?: () => void, onNew?: () => void, onMore?: () => void }} props
 */
export default function AppHeader({ onMenu, onNew, onMore }) {
  return (
    <View style={styles.header}>
      <IconButton name="menu-outline" label="메뉴" onPress={onMenu} />
      <Logo />
      <View style={styles.right}>
        <IconButton name="add" label="새 대화" onPress={onNew} />
        <IconButton name="ellipsis-vertical" size={20} label="더 보기" onPress={onMore} />
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
});
