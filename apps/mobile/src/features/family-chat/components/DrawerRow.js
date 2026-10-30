import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Switch, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 서랍의 한 행: 왼쪽 아이콘, 제목+부제, 오른쪽 chevron. 아직 동작하지 않는 행(soon)은 제목 옆에 "준비 중" 배지를 보인다.
 * kind 가 "switch" 인 행은 chevron 대신 켜기/끄기 스위치(value)를 보이고, 행 어디를 눌러도 onPress 로 바뀐다. disabled 면 누를 수 없다.
 * @param {{ row: { icon: string, title: string, subtitle?: string, state: "open" | "soon", danger?: boolean, kind?: "switch", value?: boolean, disabled?: boolean }, onPress: () => void }} props
 */
export default function DrawerRow({ row, onPress }) {
  const tint = row.danger ? colors.danger : colors.text;
  const isSwitch = row.kind === "switch";
  return (
    <Pressable
      onPress={onPress}
      disabled={isSwitch && row.disabled}
      accessibilityRole={isSwitch ? "switch" : "button"}
      accessibilityState={isSwitch ? { checked: row.value === true, disabled: row.disabled === true } : undefined}
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
      {isSwitch ? (
        <Switch
          value={row.value === true}
          disabled={row.disabled}
          onValueChange={onPress}
          trackColor={{ false: colors.divider, true: colors.peach }}
          thumbColor={colors.card}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        />
      ) : (
        <Ionicons name="chevron-forward" size={18} color={colors.placeholder} />
      )}
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
