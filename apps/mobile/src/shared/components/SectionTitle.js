import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

/**
 * 섹션 제목과 오른쪽 보조 텍스트.
 * @param {{ title: string, action?: string }} props
 */
export default function SectionTitle({ title, action }) {
  return (
    <View style={styles.row}>
      <Text style={styles.title}>{title}</Text>
      {action ? <Text style={styles.action}>{action}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: {
    ...font.section,
    color: colors.text,
  },
  action: {
    fontSize: 14,
    color: colors.textMuted,
  },
});
