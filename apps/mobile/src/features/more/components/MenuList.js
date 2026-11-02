import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 마이 페이지 세로 목록. 줄 사이에 얇은 구분선이 있고 준비 중 항목은 흐리게 보인다. badge 가 있으면 오른쪽에 작은 태그로 보인다.
 * @param {{ items: { key: string, icon: string, title: string, subtitle: string, soon?: boolean, badge?: string }[], onPressItem: (item: object) => void }} props
 * @returns {import("react").ReactElement}
 */
export default function MenuList({ items, onPressItem }) {
  return (
    <Card tone="white" style={styles.card}>
      {items.map((item, index) => (
        <Pressable
          key={item.key}
          testID={`menu-${item.key}`}
          style={[styles.row, index > 0 ? styles.divider : null, item.soon ? styles.soon : null]}
          onPress={() => onPressItem(item)}
          accessibilityRole="button"
          accessibilityLabel={[item.title, item.subtitle, item.badge].filter(Boolean).join(", ")}
          accessibilityHint={item.soon ? "준비 중이에요" : undefined}
        >
          <View style={styles.iconBox}>
            <Ionicons name={item.icon} size={20} color={colors.text} />
          </View>
          <View style={styles.texts}>
            <Text style={styles.title}>{item.title}</Text>
            <Text style={styles.subtitle}>{item.subtitle}</Text>
          </View>
          {item.badge ? <Tag label={item.badge} tone="orange" /> : null}
          <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
        </Pressable>
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { gap: 0, paddingVertical: spacing.xs },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.md,
    minHeight: 44,
  },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.divider },
  soon: { opacity: 0.6 },
  iconBox: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  texts: { flex: 1, gap: 2 },
  title: { ...font.cardTitle, color: colors.text },
  subtitle: { ...font.caption, color: colors.textMuted },
});
