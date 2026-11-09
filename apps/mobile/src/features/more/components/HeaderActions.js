import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, View } from "react-native";

import { colors, spacing } from "@/theme";

/**
 * 마이 페이지 제목 줄 오른쪽 위 버튼들. 글자·둥근 바탕 없이 아이콘만 보이고(이름은 접근성 라벨), 누르는 영역은 44x44 이상이다.
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
          <Ionicons name={item.icon} size={24} color={colors.text} />
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  item: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  pressed: { opacity: 0.7 },
});
