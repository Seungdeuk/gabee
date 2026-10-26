import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { canSend, MAX_TEXT } from "../chatUtils";

const LINE_HEIGHT = font.body.lineHeight;
const MAX_LINES = 5;

/**
 * 메시지 입력줄: 왼쪽 + 버튼(갤러리에서 사진 한 장 보내기, 보내는 중에는 진행 표시·비활성), 둥근 여러 줄 입력칸(최대 5줄), 글자가 있을 때만 켜지는 보내기 버튼.
 * 사진을 보내지 못하면 입력줄 위에 오류 문구를 보인다(다시 + 를 눌러 고르면 재시도).
 * @param {{ value: string, onChangeText: (text: string) => void, onSend: () => void, onPickPhoto: () => void, photoBusy?: boolean, photoError?: string, onDismissPhotoError?: () => void }} props
 */
export default function Composer({ value, onChangeText, onSend, onPickPhoto, photoBusy = false, photoError = "", onDismissPhotoError }) {
  const ok = canSend(value);
  return (
    <View style={styles.wrap}>
      {photoError ? (
        <View style={styles.notice} accessibilityLiveRegion="polite">
          <Text style={styles.noticeText}>{photoError}</Text>
          <Pressable onPress={onDismissPhotoError} accessibilityRole="button" accessibilityLabel="안내 닫기" hitSlop={8}>
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
          onPress={onPickPhoto}
          disabled={photoBusy}
          accessibilityRole="button"
          accessibilityLabel={photoBusy ? "사진을 보내는 중" : "사진 보내기"}
          aria-disabled={photoBusy}
          style={({ pressed }) => [styles.plus, pressed && !photoBusy && styles.pressed]}
        >
          {photoBusy ? <ActivityIndicator color={colors.accent} /> : <Ionicons name="add" size={26} color={colors.textSub} />}
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
    backgroundColor: colors.dangerSoft,
  },
  noticeText: { ...font.caption, color: colors.danger, flexShrink: 1 },
  count: { ...font.tab, color: colors.textMuted, textAlign: "right" },
  over: { color: colors.danger },
});
