import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 문의/신고를 고르는 선택 카드 두 장(아이콘 + 이름 + 한 줄 설명).
 * @param {{ options: { key: string, label: string, icon: string, desc: string }[], value: string, onChange: (key: string) => void, error?: string }} props
 * @returns {import("react").ReactElement}
 */
export default function KindPicker({ options, value, onChange, error }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.row} accessibilityRole="radiogroup">
        {options.map((o) => {
          const active = o.key === value;
          return (
            <Pressable
              key={o.key}
              onPress={() => onChange(o.key)}
              accessibilityRole="radio"
              accessibilityLabel={`${o.label}, ${o.desc}`}
              accessibilityState={{ selected: active }}
              testID={`support-kind-${o.key}`}
              style={({ pressed }) => [styles.card, active && styles.cardActive, pressed && styles.pressed]}
            >
              <View style={[styles.icon, active && styles.iconActive]}>
                <Ionicons name={o.icon} size={20} color={active ? colors.onDark : colors.accent} />
              </View>
              <Text style={styles.label}>{o.label}</Text>
              <Text style={styles.desc}>{o.desc}</Text>
            </Pressable>
          );
        })}
      </View>
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  row: { flexDirection: "row", gap: spacing.md },
  card: {
    flex: 1,
    gap: spacing.xs,
    padding: spacing.lg,
    borderRadius: radius.card,
    backgroundColor: colors.card,
    borderWidth: 1.5,
    borderColor: colors.divider,
  },
  cardActive: { borderColor: colors.accent, backgroundColor: colors.honeySoft },
  pressed: { opacity: 0.85 },
  icon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    marginBottom: spacing.xs,
  },
  iconActive: { backgroundColor: colors.accent },
  label: { ...font.cardTitle, color: colors.text },
  desc: { ...font.caption, color: colors.textMuted },
  error: { ...font.caption, color: colors.danger },
});
