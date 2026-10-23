import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { canSend, MAX_TEXT } from "../chatUtils";

/**
 * 메시지 입력줄: 여러 줄 입력창과 보내기 버튼.
 * @param {{ value: string, onChangeText: (text: string) => void, onSend: () => void }} props
 */
export default function Composer({ value, onChangeText, onSend }) {
  const ok = canSend(value);
  return (
    <View style={styles.wrap}>
      {value.length > MAX_TEXT - 200 ? (
        <Text style={[styles.count, value.length > MAX_TEXT && styles.over]}>
          {value.length} / {MAX_TEXT}
        </Text>
      ) : null}
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChangeText}
          placeholder="메시지를 입력하세요"
          placeholderTextColor={colors.placeholder}
          multiline
          accessibilityLabel="메시지 입력"
        />
        <Pressable
          onPress={onSend}
          disabled={!ok}
          accessibilityRole="button"
          accessibilityLabel="보내기"
          aria-disabled={!ok}
          style={({ pressed }) => [styles.send, !ok && styles.sendOff, pressed && ok && styles.pressed]}
        >
          <Ionicons name="arrow-up" size={22} color={ok ? colors.text : colors.disabled} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    backgroundColor: colors.background,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
    gap: spacing.xs,
  },
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    ...font.body,
    color: colors.text,
  },
  send: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  sendOff: { backgroundColor: colors.honeySoft },
  pressed: { opacity: 0.85 },
  count: { ...font.tab, color: colors.textMuted, textAlign: "right" },
  over: { color: colors.danger },
});
