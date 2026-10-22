import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, spacing } from "@/theme";

import { DOT_COLOR } from "../constants";

/**
 * 등록 화면의 입력 한 칸: 라벨(+ 작은 안내) 줄 아래에 입력 칸. 라벨 줄 오른쪽에 글자 버튼을 둘 수 있다.
 * @param {{ label: string, hint?: string, action?: string, onAction?: () => void, children: import("react").ReactNode }} props
 */
export function FormField({ label, hint, action, onAction, children }) {
  return (
    <View style={styles.field}>
      <View style={styles.labelRow}>
        <Text style={styles.label}>
          {label}
          {hint ? <Text style={styles.hint}>{`  ${hint}`}</Text> : null}
        </Text>
        {action ? (
          <Pressable onPress={onAction} accessibilityRole="button">
            <Text style={styles.action}>{action}</Text>
          </Pressable>
        ) : null}
      </View>
      {children}
    </View>
  );
}

/**
 * 글자를 직접 쓰는 입력 칸.
 * @param {{ value: string, onChangeText: (text: string) => void, placeholder?: string, multiline?: boolean }} props
 */
export function TextBox({ value, onChangeText, placeholder, multiline = false }) {
  return (
    <TextInput
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={colors.textMuted}
      multiline={multiline}
      style={[styles.box, multiline && styles.multiline]}
    />
  );
}

/**
 * 눌러서 시트를 여는 입력 칸. 값이 없으면 안내 글자, 오른쪽에 › 표시.
 * @param {{ value?: string, placeholder?: string, onPress?: () => void }} props
 */
export function PressBox({ value, placeholder, onPress }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" style={[styles.box, styles.pressBox]}>
      <Text style={[styles.value, !value && styles.placeholder]}>{value || placeholder || ""}</Text>
      <Text style={styles.chevron}>›</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  field: { gap: spacing.xs },
  labelRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  hint: { ...font.caption, fontWeight: "400", color: colors.textMuted },
  action: { ...font.caption, fontWeight: "500", color: DOT_COLOR },
  box: {
    minHeight: 40,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 16,
    color: colors.text,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
  },
  multiline: { minHeight: 72, textAlignVertical: "top" },
  pressBox: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  value: { flex: 1, fontSize: 16, color: colors.text },
  placeholder: { color: colors.textMuted },
  chevron: { fontSize: 18, color: colors.textMuted },
});
