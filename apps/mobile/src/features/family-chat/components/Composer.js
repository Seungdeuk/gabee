import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { canSend, MAX_TEXT } from "../chatUtils";

const LINE_HEIGHT = font.body.lineHeight;
const MAX_LINES = 5;

/**
 * 메시지 입력줄: 왼쪽 + 버튼(사진·파일은 준비 중 안내), 둥근 여러 줄 입력칸(최대 5줄), 글자가 있을 때만 켜지는 보내기 버튼.
 * @param {{ value: string, onChangeText: (text: string) => void, onSend: () => void }} props
 */
export default function Composer({ value, onChangeText, onSend }) {
  const ok = canSend(value);
  const [notice, setNotice] = useState(false);
  return (
    <View style={styles.wrap}>
      {notice ? (
        <View style={styles.notice} accessibilityLiveRegion="polite">
          <Text style={styles.noticeText}>사진·파일 보내기는 준비 중이에요</Text>
          <Pressable onPress={() => setNotice(false)} accessibilityRole="button" accessibilityLabel="안내 닫기" hitSlop={8}>
            <Ionicons name="close" size={18} color={colors.textMuted} />
          </Pressable>
        </View>
      ) : null}
      {value.length > MAX_TEXT - 200 ? (
        <Text style={[styles.count, value.length > MAX_TEXT && styles.over]}>
          {value.length} / {MAX_TEXT}
        </Text>
      ) : null}
      <View style={styles.row}>
        <Pressable
          onPress={() => setNotice((v) => !v)}
          accessibilityRole="button"
          accessibilityLabel="사진·파일 추가 (준비 중)"
          style={({ pressed }) => [styles.plus, pressed && styles.pressed]}
        >
          <Ionicons name="add" size={26} color={colors.textSub} />
        </Pressable>
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
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    backgroundColor: colors.card,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
    gap: spacing.xs,
  },
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.xs },
  plus: { width: 40, height: 40, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: LINE_HEIGHT * MAX_LINES + spacing.sm * 2,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.card,
    backgroundColor: colors.surface,
    ...font.body,
    color: colors.text,
  },
  send: { width: 40, height: 40, borderRadius: radius.pill, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  sendOff: { backgroundColor: colors.divider },
  pressed: { opacity: 0.85 },
  notice: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.honeySoft,
  },
  noticeText: { ...font.caption, color: colors.textSub },
  count: { ...font.tab, color: colors.textMuted, textAlign: "right" },
  over: { color: colors.danger },
});
