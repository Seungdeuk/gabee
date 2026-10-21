import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

/**
 * 탭 화면의 큰 제목: 왼쪽에 제목과 한 줄 설명, 오른쪽에 아이콘 버튼들.
 * @param {{ title: string, subtitle?: string, right?: import("react").ReactNode, left?: import("react").ReactNode }} props
 */
export default function PageHeader({ title, subtitle, right, left }) {
  return (
    <View style={styles.header}>
      {left ? <View style={styles.left}>{left}</View> : null}
      <View style={styles.text}>
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      <View style={styles.right}>{right}</View>
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
  right: {
    flexDirection: "row",
    marginRight: -10,
  },
});
