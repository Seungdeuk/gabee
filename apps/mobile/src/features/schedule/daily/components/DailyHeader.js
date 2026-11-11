import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

/**
 * 데일리 체크 하위 화면(편집·항목·가족 순서 바꾸기)의 상단 막대: 왼쪽 뒤로·닫기, 가운데 제목, 오른쪽 글자 버튼.
 * @param {{ title: string, onBack: () => void, backIcon?: "chevron-back" | "close", backLabel: string, right?: import("react").ReactNode }} props
 */
export default function DailyHeader({ title, onBack, backIcon = "chevron-back", backLabel, right }) {
  return (
    <View style={styles.bar}>
      <Pressable onPress={onBack} style={styles.side} accessibilityRole="button" accessibilityLabel={backLabel} hitSlop={6}>
        <Ionicons name={backIcon} size={24} color={colors.text} />
      </Pressable>
      <Text style={styles.title} accessibilityRole="header" numberOfLines={1}>
        {title}
      </Text>
      <View style={styles.sideRight}>{right}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    height: 60,
    paddingHorizontal: 8,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.background, // 구분선 없음(시안 Edit/Reorder 상단 막대는 선이 없다)
  },
  side: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22 },
  sideRight: { minWidth: 44, height: 44, alignItems: "flex-end", justifyContent: "center" },
  title: { ...font.title, fontSize: 18, color: colors.text, flex: 1, textAlign: "center" },
});
