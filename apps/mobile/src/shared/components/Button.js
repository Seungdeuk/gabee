import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text } from "react-native";

import { colors, radius } from "@/theme";

const variants = {
  primary: { backgroundColor: colors.peach, color: colors.text },
  secondary: { backgroundColor: colors.card, color: colors.text, borderWidth: 1, borderColor: colors.border },
  ghost: { backgroundColor: colors.honeySoft, color: colors.textMuted },
};

/**
 * 버튼. 기본(peach)·보조(흰색 테두리)·옅은(ghost) 세 가지, 작은 크기(small)는 목록 안에서 쓴다.
 * icon 에 Ionicons 이름을 주면 글자 앞에 같은 색으로 그린다.
 * @param {{ label: string, a11yLabel?: string, onPress?: () => void, variant?: keyof typeof variants, small?: boolean, selected?: boolean, disabled?: boolean, icon?: string, testID?: string }} props
 */
export default function Button({
  label,
  a11yLabel,
  onPress,
  variant = "primary",
  small = false,
  selected = false,
  disabled = false,
  icon,
  testID,
}) {
  const { color, ...box } = disabled ? { ...variants.ghost, color: colors.disabled } : variants[variant];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={a11yLabel ?? label}
      aria-disabled={disabled}
      aria-selected={selected}
      style={({ pressed }) => [
        styles.button,
        small ? styles.small : styles.large,
        box,
        icon && styles.withIcon,
        selected && styles.selected,
        pressed && styles.pressed,
      ]}
    >
      {icon ? <Ionicons name={icon} size={small ? 16 : 20} color={color} /> : null}
      <Text style={[small ? styles.smallText : styles.largeText, { color }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: { alignItems: "center", justifyContent: "center" },
  withIcon: { flexDirection: "row", gap: 8 },
  large: { height: 56, borderRadius: radius.button, paddingHorizontal: 20 },
  small: { height: 40, borderRadius: 12, paddingHorizontal: 14 },
  largeText: { fontSize: 16, fontWeight: "700" },
  smallText: { fontSize: 14, fontWeight: "700" },
  selected: { backgroundColor: colors.peach, borderColor: colors.peach },
  pressed: { opacity: 0.85 },
});
