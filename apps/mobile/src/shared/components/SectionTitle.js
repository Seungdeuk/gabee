import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

/**
 * 섹션 제목과 오른쪽 보조 링크.
 * @param {{ title: string, action?: string, onAction?: () => void }} props
 */
export default function SectionTitle({ title, action, onAction }) {
  return (
    <View style={styles.row}>
      <Text style={styles.title}>{title}</Text>
      {action ? (
        <Pressable onPress={onAction} style={styles.actionBox} accessibilityRole="button">
          <Text style={styles.action}>{action}</Text>
        </Pressable>
      ) : null}
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
  actionBox: {
    minHeight: 44,
    justifyContent: "center",
  },
  action: {
    fontSize: 13,
    fontWeight: "700",
    color: colors.text,
  },
});
