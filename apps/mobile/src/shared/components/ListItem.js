import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

const iconTones = {
  gray: { backgroundColor: colors.honeySoft, color: colors.textMuted },
  blue: { backgroundColor: colors.surfaceStrong, color: colors.text },
  green: { backgroundColor: colors.successSoft, color: colors.success },
  orange: { backgroundColor: colors.surfaceStrong, color: colors.accent },
  red: { backgroundColor: colors.dangerSoft, color: colors.danger },
  purple: { backgroundColor: colors.peachSoft, color: colors.purple },
};

/**
 * 아이콘 + 제목/부제 + 오른쪽 영역으로 이루어진 목록 행.
 * @param {{ icon?: string, tone?: keyof typeof iconTones, title: string, subtitle?: string, right?: import("react").ReactNode }} props
 */
export default function ListItem({ icon, tone = "gray", title, subtitle, right }) {
  const { backgroundColor, color } = iconTones[tone];
  return (
    <View style={styles.row}>
      {icon ? (
        <View style={[styles.icon, { backgroundColor }]}>
          <Ionicons name={icon} size={20} color={color} />
        </View>
      ) : null}
      <View style={styles.main}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {typeof right === "string" ? <Text style={styles.right}>{right}</Text> : right}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    minHeight: 44,
  },
  icon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  main: {
    flex: 1,
    gap: 2,
  },
  title: {
    ...font.bodyStrong,
    color: colors.text,
  },
  subtitle: {
    ...font.caption,
    color: colors.textMuted,
  },
  right: {
    ...font.bodyStrong,
    fontWeight: "700",
    color: colors.text,
  },
});
