import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 서랍의 한 행: 왼쪽 아이콘, 제목+부제, 오른쪽 chevron. 아직 동작하지 않는 행(soon)은 제목 옆에 "준비 중" 배지를 보인다.
 * @param {{ row: { icon: string, title: string, subtitle?: string, state: "open" | "soon", danger?: boolean }, onPress: () => void }} props
 */
export default function DrawerRow({ row, onPress }) {
  const tint = row.danger ? colors.danger : colors.text;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={row.state === "soon" ? `${row.title}, 준비 중` : row.title}
      accessibilityHint={row.subtitle || undefined}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <Ionicons name={row.icon} size={22} color={row.danger ? colors.danger : colors.textSub} />
      <View style={styles.texts}>
        <View style={styles.titleLine}>
          <Text style={[styles.title, { color: tint }]} numberOfLines={1}>
            {row.title}
          </Text>
          {row.state === "soon" ? (
            <View style={styles.badge}>
              <Text style={styles.badgeText}>준비 중</Text>
            </View>
          ) : null}
        </View>
        {row.subtitle ? (
          <Text style={styles.subtitle} numberOfLines={1}>
            {row.subtitle}
          </Text>
        ) : null}
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.placeholder} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  pressed: { backgroundColor: colors.surface },
  texts: { flex: 1, minWidth: 0 },
  titleLine: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { ...font.bodyStrong, flexShrink: 1 },
  subtitle: { ...font.caption, color: colors.textMuted },
  badge: { paddingHorizontal: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.surfaceStrong },
  badgeText: { ...font.tab, color: colors.textSub },
});
