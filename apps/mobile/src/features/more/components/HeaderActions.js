import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 마이 페이지 제목 줄 오른쪽 위 버튼들. 둥근 바탕 안의 아이콘 아래에 이름이 함께 보인다(알림설정·환경설정).
 * @param {{ items: { key: string, icon: string, label: string, onPress: () => void }[] }} props
 * @returns {import("react").ReactElement}
 */
export default function HeaderActions({ items }) {
  return (
    <View style={styles.row}>
      {items.map((item) => (
        <Pressable
          key={item.key}
          testID={`header-${item.key}`}
          onPress={item.onPress}
          accessibilityRole="button"
          accessibilityLabel={item.label}
          style={({ pressed }) => [styles.item, pressed && styles.pressed]}
        >
          <View style={styles.bubble}>
            <Ionicons name={item.icon} size={22} color={colors.text} />
          </View>
          <Text style={styles.label} numberOfLines={1}>
            {item.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  item: { alignItems: "center", gap: spacing.xs, minWidth: 48 },
  bubble: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  label: { ...font.caption, lineHeight: 16, color: colors.textSub },
  pressed: { opacity: 0.7 },
});
