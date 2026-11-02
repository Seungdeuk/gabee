import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 마이 페이지 바로가기 카드 격자(2열). 준비 중 항목은 흐리게 보인다.
 * @param {{ items: { key: string, icon: string, title: string, subtitle: string, soon?: boolean }[], onPressItem: (item: object) => void }} props
 * @returns {import("react").ReactElement}
 */
export default function ShortcutGrid({ items, onPressItem }) {
  return (
    <View style={styles.grid}>
      {items.map((item) => (
        <Pressable
          key={item.key}
          testID={`shortcut-${item.key}`}
          style={[styles.card, item.soon ? styles.soon : null]}
          onPress={() => onPressItem(item)}
          accessibilityRole="button"
          accessibilityLabel={`${item.title}, ${item.subtitle}`}
          accessibilityHint={item.soon ? "준비 중이에요" : undefined}
        >
          <Ionicons name={item.icon} size={22} color={colors.text} />
          <View style={styles.texts}>
            <Text style={styles.title}>{item.title}</Text>
            <Text style={styles.subtitle}>{item.subtitle}</Text>
          </View>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
  },
  card: {
    flexGrow: 1,
    flexBasis: "45%",
    minWidth: 0,
    gap: spacing.md,
    padding: spacing.lg,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.divider,
    borderRadius: radius.card,
  },
  soon: { opacity: 0.6 },
  texts: { gap: spacing.xs },
  title: { ...font.cardTitle, color: colors.text },
  subtitle: { ...font.caption, color: colors.textMuted },
});
