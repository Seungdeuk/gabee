import { StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

/**
 * 화면 상단 헤더 (높이 60).
 * @param {{ title: string, left?: import("react").ReactNode, right?: import("react").ReactNode }} props
 */
export default function ScreenHeader({ title, left, right }) {
  return (
    <View style={styles.header}>
      <View style={styles.side}>{left}</View>
      <Text style={styles.title}>{title}</Text>
      <View style={[styles.side, styles.sideRight]}>{right}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    height: 60,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    backgroundColor: colors.background,
  },
  side: {
    width: 52,
    alignItems: "flex-start",
  },
  sideRight: {
    alignItems: "flex-end",
  },
  title: {
    ...font.title,
    flex: 1,
    textAlign: "center",
    color: colors.text,
  },
});
