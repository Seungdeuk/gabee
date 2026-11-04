import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Card from "@/shared/components/Card";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 마이 페이지 바로가기: 하나의 카드 안에 같은 폭으로 늘어선 칸이고 칸 사이에 세로 구분선이 있다. 아이콘 아래에 이름만 보인다(설명은 접근성 읽기에만 쓴다).
 * 준비 중 항목은 흐리게 보이고, badge 가 있으면 아이콘 오른쪽 위에 작은 숫자 표시가 붙는다.
 * @param {{ items: { key: string, icon: string, title: string, subtitle: string, soon?: boolean, badge?: string }[], onPressItem: (item: object) => void }} props
 * @returns {import("react").ReactElement}
 */
export default function ShortcutGrid({ items, onPressItem }) {
  return (
    <Card tone="white" style={styles.card}>
      {items.map((item, index) => (
        <Pressable
          key={item.key}
          testID={`shortcut-${item.key}`}
          style={[styles.cell, index > 0 ? styles.divider : null, item.soon ? styles.soon : null]}
          onPress={() => onPressItem(item)}
          accessibilityRole="button"
          accessibilityLabel={[item.title, item.subtitle, item.badge ? `${item.badge}건` : ""].filter(Boolean).join(", ")}
          accessibilityHint={item.soon ? "준비 중이에요" : undefined}
        >
          <View style={styles.icon}>
            <Ionicons name={item.icon} size={30} color={colors.accent} />
            {item.badge ? (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{item.badge}</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.title} numberOfLines={1}>
            {item.title}
          </Text>
        </Pressable>
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", gap: 0, paddingVertical: spacing.md, paddingHorizontal: 0 },
  cell: { flex: 1, alignItems: "center", gap: spacing.sm, minHeight: 64, justifyContent: "center" },
  divider: { borderLeftWidth: StyleSheet.hairlineWidth, borderLeftColor: colors.divider },
  icon: { width: 44, height: 36, alignItems: "center", justifyContent: "center" },
  badge: { position: "absolute", top: -spacing.xs, right: -spacing.xs, minWidth: 20, height: 20, paddingHorizontal: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  badgeText: { ...font.caption, lineHeight: 16, color: colors.text },
  soon: { opacity: 0.6 },
  title: { ...font.caption, color: colors.text },
});
