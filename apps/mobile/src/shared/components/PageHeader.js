import { StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

import { SETTINGS_EDGE_GAP, SETTINGS_RAISE } from "./SettingsButton";

/**
 * 탭 화면의 큰 제목: 왼쪽에 제목과 한 줄 설명, 오른쪽에 아이콘 버튼들.
 * centered 가 true 면 제목과 설명을 가운데에 놓고, 왼쪽 버튼은 왼쪽 끝에 따로 붙인다.
 * @param {{ title: string, subtitle?: string, right?: import("react").ReactNode, left?: import("react").ReactNode, centered?: boolean }} props
 */
export default function PageHeader({ title, subtitle, right, left, centered = false }) {
  return (
    <View style={[styles.header, centered && styles.headerCentered]}>
      {left ? <View style={[styles.left, centered && styles.leftCentered]}>{left}</View> : null}
      <View style={[styles.text, centered && styles.textCentered]}>
        <Text style={[styles.title, centered && styles.centerText]} accessibilityRole="header">
          {title}
        </Text>
        {subtitle ? <Text style={[styles.subtitle, centered && styles.centerText]}>{subtitle}</Text> : null}
      </View>
      <View style={[styles.right, centered && styles.rightCentered]}>
        {right}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 8,
  },
  text: {
    flex: 1,
    gap: 4,
  },
  title: {
    ...font.page,
    color: colors.text,
  },
  subtitle: {
    fontSize: 13,
    color: colors.textMuted,
  },
  left: {
    marginLeft: -10,
    marginTop: -4,
  },
  headerCentered: { justifyContent: "center" },
  leftCentered: { position: "absolute", left: 0, zIndex: 1 },
  textCentered: { paddingHorizontal: 44 }, // 양쪽 버튼과 겹치지 않게 비운다
  centerText: { textAlign: "center" },
  rightCentered: { position: "absolute", right: 0 },
  // 제목 줄 위치는 그대로 두고 버튼만 상단바 높이에 맞춰 올린다(transform 은 배치에 영향이 없다)
  right: {
    flexDirection: "row",
    marginRight: SETTINGS_EDGE_GAP - spacing.xl,
    transform: [{ translateY: -SETTINGS_RAISE }],
  },
});
