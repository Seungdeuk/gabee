import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef } from "react";
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { canSend, MAX_TEXT, shouldSendOnEnter } from "../chatUtils";
import { replyLine } from "../messageActions";

const LINE_HEIGHT = font.body.lineHeight;
const MAX_LINES = 5;

/**
 * 메시지 입력줄: 왼쪽 + 버튼(갤러리에서 사진 한 장 보내기, 보내는 중에는 진행 표시·비활성), 둥근 여러 줄 입력칸(최대 5줄), 글자가 있을 때만 켜지는 보내기 버튼.
 * 사진을 보내지 못하면 입력줄 위에 오류 문구를 보인다(다시 + 를 눌러 고르면 재시도).
 * 답장 중이면(replyTo) 입력줄 위에 "○○에게 답장" 바(원본 한 줄 미리보기, 닫기)가 뜨고 입력칸에 커서가 간다.
 * @param {{ value: string, onChangeText: (text: string) => void, onSend: () => void, onPickPhoto: () => void, photoBusy?: boolean, photoError?: string, onDismissPhotoError?: () => void, replyTo?: { id: number, user_name: string, text: string, deleted: boolean, has_attachment: boolean } | null, onCancelReply?: () => void }} props
 */
export default function Composer({ value, onChangeText, onSend, onPickPhoto, photoBusy = false, photoError = "", onDismissPhotoError, replyTo = null, onCancelReply }) {
  const ok = canSend(value);
  const inputRef = useRef(null);
  const replyId = replyTo?.id ?? null;
  useEffect(() => {
    if (replyId != null) inputRef.current?.focus(); // 답장을 시작하면 바로 쓸 수 있게
  }, [replyId]);
  // 웹(키보드)에서는 Enter 로 보내고 Shift+Enter 로 줄을 바꾼다. 폰 화면 키보드의 Enter 는 줄바꿈 그대로
  const onKeyPress = (event) => {
    if (!shouldSendOnEnter(event.nativeEvent, Platform.OS)) return;
    event.preventDefault?.();
    if (ok) onSend();
  };
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
      {replyTo ? (
        <View style={styles.replyBar} accessibilityLiveRegion="polite">
          <View style={styles.replyTexts}>
            <Text style={styles.replyName} numberOfLines={1}>{`${replyTo.user_name}에게 답장`}</Text>
            <Text style={styles.replyLine} numberOfLines={1}>
              {replyLine(replyTo)}
            </Text>
          </View>
          <Pressable onPress={onCancelReply} accessibilityRole="button" accessibilityLabel="답장 취소" hitSlop={spacing.sm}>
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
          ref={inputRef}
          style={styles.input}
          value={value}
          onChangeText={onChangeText}
          placeholder="메시지를 입력하세요"
          placeholderTextColor={colors.placeholder}
          multiline
          onKeyPress={onKeyPress}
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
  replyBar: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginHorizontal: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderLeftWidth: 3, borderLeftColor: colors.accent, borderRadius: radius.sm, backgroundColor: colors.surface },
  replyTexts: { flex: 1, minWidth: 0 },
  replyName: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub },
  replyLine: { ...font.caption, color: colors.text },
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
    // lineHeight 를 주면 안드로이드 입력칸의 글자·안내 문구가 위로 밀려 윗부분이 잘린다
    fontSize: font.body.fontSize,
    fontFamily: font.body.fontFamily,
    color: colors.text,
    textAlignVertical: "center",
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
