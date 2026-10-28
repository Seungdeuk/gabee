import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

/**
 * 구역 제목 + 개수(예: 2/3) + 오른쪽 동작. 제목을 누르면 접고 펼친다.
 * @param {{ title: string, count?: string, collapsed?: boolean, onToggle?: () => void, right?: import("react").ReactNode }} props
 */
export default function SectionHeader({ title, count, collapsed = false, onToggle, right }) {
  const arrow = onToggle ? (collapsed ? " ▸" : " ▾") : "";
  return (
    <View style={styles.row}>
      <Pressable onPress={onToggle} disabled={!onToggle} style={styles.title}>
        <Text style={styles.text}>
          {title}
          {count ? <Text style={styles.count}> {count}</Text> : null}
          {arrow}
        </Text>
      </Pressable>
      {right}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 28 },
  title: { flexShrink: 1 },
  text: { ...font.section, color: colors.text },
  count: { ...font.bodyStrong, color: colors.textMuted },
});
