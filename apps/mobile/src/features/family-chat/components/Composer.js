import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Keyboard, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { canSend, MAX_TEXT, shouldSendOnEnter } from "../chatUtils";
import { isPlusFile, isPlusPhoto, PLUS_SOON_MS, PLUS_SOON_NOTICE } from "../fileUtils";
import { replyLine } from "../messageActions";
import PlusSheet from "./PlusSheet";

const LINE_HEIGHT = font.body.lineHeight;
const MAX_LINES = 5;
const INNER_BTN = 36; // 입력칸 안 버튼(문서·보내기)의 한 변
const INNER_SLOT = INNER_BTN; // 오른쪽 자리: 버튼 한 개 폭으로 고정해 글자를 쓰기 시작해도 글자 영역이 흔들리지 않는다

/**
 * 메시지 입력줄: 왼쪽 + 버튼(아래에서 올라오는 메뉴 시트: 사진·파일·일정·정산·안부 — 사진은 바로 갤러리에서 한 장, 파일은 문서 파일 한 개를 고르고, 일정·정산·안부는 아직 "준비 중이에요" 안내), 둥근 여러 줄 입력칸(최대 5줄), 입력칸 오른쪽 안의 보내기 버튼(글자가 있을 때만 켜짐).
 * 사진·파일을 보내는 중에는 + 버튼이 진행 표시·비활성이다. 보내지 못하면 입력줄 위에 오류 문구를 보인다(다시 눌러 재시도).
 * 답장 중이면(replyTo) 입력줄 위에 "○○에게 답장" 바(원본 한 줄 미리보기, 닫기)가 뜨고 입력칸에 커서가 간다.
 * @param {{ value: string, onChangeText: (text: string) => void, onSend: () => void, onPickPhoto: () => void, onPickFile?: () => void, photoBusy?: boolean, fileBusy?: boolean, photoError?: string, onDismissPhotoError?: () => void, replyTo?: { id: number, user_name: string, text: string, deleted: boolean, has_attachment: boolean } | null, onCancelReply?: () => void }} props
 */
export default function Composer({ value, onChangeText, onSend, onPickPhoto, onPickFile, photoBusy = false, fileBusy = false, photoError = "", onDismissPhotoError, replyTo = null, onCancelReply }) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [soon, setSoon] = useState(false); // "준비 중이에요" 안내 줄
  useEffect(() => {
    if (!soon) return undefined;
    const timer = setTimeout(() => setSoon(false), PLUS_SOON_MS); // 안내는 몇 초 뒤 저절로 사라진다
    return () => clearTimeout(timer);
  }, [soon]);
  const ok = canSend(value);
  const sending = photoBusy || fileBusy; // 사진·파일을 보내는 동안은 + 버튼이 진행 표시
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
      {soon ? (
        <View style={styles.soon} accessibilityLiveRegion="polite">
          <Text style={styles.soonText}>{PLUS_SOON_NOTICE}</Text>
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
          onPress={() => {
            Keyboard.dismiss(); // 키보드가 시트를 가리지 않게
            setSheetOpen(true);
          }}
          disabled={sending}
          accessibilityRole="button"
          accessibilityLabel={photoBusy ? "사진을 보내는 중" : fileBusy ? "파일을 보내는 중" : "더 보기 메뉴"}
          aria-disabled={sending}
          style={({ pressed }) => [styles.plus, pressed && !sending && styles.pressed]}
        >
          {sending ? <ActivityIndicator color={colors.accent} /> : <Ionicons name="add" size={26} color={colors.textSub} />}
        </Pressable>
        <View style={styles.inputBox}>
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
          <View style={styles.slot}>
            <Pressable
              onPress={onSend}
              disabled={!ok}
              accessibilityRole="button"
              accessibilityLabel="보내기"
              aria-disabled={!ok}
              style={({ pressed }) => [styles.inner, styles.send, !ok && styles.sendOff, pressed && ok && styles.pressed]}
            >
              <Ionicons name="arrow-up" size={20} color={ok ? colors.text : colors.disabled} />
            </Pressable>
          </View>
        </View>
      </View>
      <PlusSheet
        visible={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onSelect={(key) => {
          setSheetOpen(false);
          if (isPlusPhoto(key)) onPickPhoto();
          else if (isPlusFile(key)) onPickFile?.();
          else setSoon(true); // 일정·정산·안부의 실제 기능은 이후 작업: 지금은 안내만
        }}
      />
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
  inputBox: { flex: 1, flexDirection: "row", alignItems: "flex-end", borderRadius: radius.card, backgroundColor: colors.surface },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: LINE_HEIGHT * MAX_LINES + spacing.sm * 2,
    paddingLeft: spacing.lg,
    paddingRight: spacing.xs,
    paddingVertical: spacing.sm,
    // lineHeight 를 주면 안드로이드 입력칸의 글자·안내 문구가 위로 밀려 윗부분이 잘린다
    fontSize: font.body.fontSize,
    fontFamily: font.body.fontFamily,
    color: colors.text,
    textAlignVertical: "center",
  },
  slot: { width: INNER_SLOT, height: 40, flexDirection: "row", alignItems: "center", justifyContent: "flex-end", paddingRight: spacing.xs },
  inner: { width: INNER_BTN, height: INNER_BTN, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  send: { backgroundColor: colors.peach },
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
  soon: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.md, backgroundColor: colors.surface },
  soonText: { ...font.caption, color: colors.textSub },
  noticeText: { ...font.caption, color: colors.danger, flexShrink: 1 },
  count: { ...font.tab, color: colors.textMuted, textAlign: "right" },
  over: { color: colors.danger },
});
