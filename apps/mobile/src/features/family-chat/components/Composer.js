import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, InteractionManager, Keyboard, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { canSend, MAX_TEXT, shouldSendOnEnter } from "../chatUtils";
import { isPlusFile, isPlusPhoto, isPlusShare, PLUS_SOON_MS, PLUS_SOON_NOTICE, plusShareKind } from "../fileUtils";
import { replyLine } from "../messageActions";
import { MENTION_EXAMPLES, mentionHintsVisible } from "../mention";
import { scheduleAfterSheetClose } from "../shareUtils";
import PlusSheet from "./PlusSheet";

const LINE_HEIGHT = font.body.lineHeight;
const MAX_LINES = 5;
const ROW_H = LINE_HEIGHT + (spacing.xs + 2) * 2; // 입력 줄의 한 줄 높이 = 말풍선 한 줄 높이(글자 줄 높이 + 위아래 여백). + 버튼, 입력칸, 보내기 자리가 모두 이 높이
const INNER_BTN = ROW_H - spacing.xs * 2; // 입력칸 안 버튼(문서·보내기)의 한 변
const MAX_H = LINE_HEIGHT * MAX_LINES + spacing.xs * 2; // 입력칸 최대 높이(5줄)
const INNER_SLOT = INNER_BTN; // 오른쪽 자리: 버튼 한 개 폭으로 고정해 글자를 쓰기 시작해도 글자 영역이 흔들리지 않는다

/**
 * 메시지 입력줄: 왼쪽 + 버튼(아래에서 올라오는 메뉴 시트: 사진·파일·일정·정산·안부 — 사진은 바로 갤러리에서 한 장, 파일은 문서 파일 한 개를 고르고, 일정·정산은 공유 시트를 열어(onShare) 내 일정·정산 카드를 보내고, 안부는 아직 "준비 중이에요" 안내), 둥근 여러 줄 입력칸(최대 5줄), 입력칸 오른쪽 안의 보내기 버튼(글자가 있을 때만 켜짐).
 * 사진·파일·공유 카드를 보내는 중에는 + 버튼이 진행 표시·비활성이다. 보내지 못하면 입력줄 위에 오류 문구를 보인다(다시 눌러 재시도).
 * 답장 중이면(replyTo) 입력줄 위에 "○○에게 답장" 바(원본 한 줄 미리보기, 닫기)가 뜨고 입력칸에 커서가 간다.
 * @param {{ value: string, onChangeText: (text: string) => void, onSend: () => void, onPickPhoto: () => void, onPickFile?: () => void, onShare?: (kind: "event" | "settlement") => void, onPlusOpen?: () => void, photoBusy?: boolean, fileBusy?: boolean, shareBusy?: boolean, photoError?: string, onDismissPhotoError?: () => void, replyTo?: { id: number, user_name: string, text: string, deleted: boolean, has_attachment: boolean } | null, onCancelReply?: () => void, direct?: boolean }} props
 */
export default function Composer({ value, onChangeText, onSend, onPickPhoto, onPickFile, onShare, onPlusOpen, photoBusy = false, fileBusy = false, shareBusy = false, photoError = "", onDismissPhotoError, replyTo = null, onCancelReply, direct = false }) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [soon, setSoon] = useState(false); // "준비 중이에요" 안내 줄
  const handoff = useRef(null); // "+" 시트가 닫힌 뒤 공유 시트를 열도록 예약한 일의 취소 함수
  useEffect(() => () => handoff.current?.(), []); // 화면을 떠나면 예약을 취소한다
  useEffect(() => {
    if (!soon) return undefined;
    const timer = setTimeout(() => setSoon(false), PLUS_SOON_MS); // 안내는 몇 초 뒤 저절로 사라진다
    return () => clearTimeout(timer);
  }, [soon]);
  const ok = canSend(value);
  const sending = photoBusy || fileBusy || shareBusy; // 사진·파일·공유 카드를 보내는 동안은 + 버튼이 진행 표시
  const inputRef = useRef(null);
  const [inputH, setInputH] = useState(ROW_H); // 입력칸 높이: 글자 높이에 맞추되 한 줄일 때는 말풍선과 같은 높이로 고정(안드로이드 기본 여백 때문에 더 커지지 않게)
  const [sel, setSel] = useState(null); // 예시를 채운 직후에만 커서를 끝으로 둔다(안드로이드). 평소에는 제어하지 않는다
  const hintsOn = mentionHintsVisible(value); // `@` 를 치면 @가비 예시 목록
  const replyId = replyTo?.id ?? null;
  // 웹: onContentSizeChange 의 높이는 입력칸의 scrollHeight(위아래 여백 포함, 현재 높이 이상)라서, 여백을 또 더하면 글자를 쓰거나 지울 때마다 입력칸이 커지기만 한다.
  // 그래서 웹에서는 값이 바뀔 때마다 높이를 한 줄로 되돌린 뒤 scrollHeight 를 재서 맞춘다(지우면 줄어든다).
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const el = inputRef.current;
    if (!el?.style) return;
    el.style.height = `${ROW_H}px`;
    const h = Math.min(MAX_H, Math.max(ROW_H, el.scrollHeight));
    el.style.height = `${h}px`; // 높이가 그대로여서 React 가 다시 쓰지 않아도 되돌려 둔 한 줄 높이가 남지 않게 직접 맞춘다
    setInputH(h);
  }, [value]);
  useEffect(() => {
    if (replyId != null) inputRef.current?.focus(); // 답장을 시작하면 바로 쓸 수 있게
  }, [replyId]);
  // 웹(키보드)에서는 Enter 로 보내고 Shift+Enter 로 줄을 바꾼다. 폰 화면 키보드의 Enter 는 줄바꿈 그대로
  const onKeyPress = (event) => {
    if (!shouldSendOnEnter(event.nativeEvent, Platform.OS)) return;
    event.preventDefault?.();
    if (ok) onSend();
  };
  const pickExample = (text) => {
    setSel({ start: text.length, end: text.length });
    onChangeText(text); // 보내지 않고 입력창에만 채운다. 고쳐서 보낼 수 있다
    inputRef.current?.focus();
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
      {hintsOn ? (
        <View style={styles.hintBox} accessibilityLabel="@가비 기능 예시">
        <ScrollView style={styles.hints} keyboardShouldPersistTaps="always" nestedScrollEnabled>
          {MENTION_EXAMPLES.map((ex) => (
            <Pressable
              key={ex.key}
              onPress={() => pickExample(ex.text)}
              accessibilityRole="button"
              accessibilityLabel={`예시 입력: ${ex.text}`}
              style={({ pressed }) => [styles.hint, pressed && styles.pressed]}
            >
              <View style={styles.chip}>
                <Text style={styles.chipText} numberOfLines={1}>
                  {ex.category}
                </Text>
              </View>
              <Text style={styles.hintText} numberOfLines={2}>
                {ex.text}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
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
            handoff.current?.(); // 예약 중인 공유 창 넘기기가 "+" 시트 위에 겹쳐 뜨지 않게 취소한다
            onPlusOpen?.(); // 부모가 예약해 둔 다른 창 열기(공유 시트 다시 열기 등)도 취소할 수 있게 알린다
            Keyboard.dismiss(); // 키보드가 시트를 가리지 않게
            setSheetOpen(true);
          }}
          disabled={sending}
          accessibilityRole="button"
          accessibilityLabel={photoBusy ? "사진을 보내는 중" : fileBusy ? "파일을 보내는 중" : shareBusy ? "공유 카드를 보내는 중" : "더 보기 메뉴"}
          aria-disabled={sending}
          style={({ pressed }) => [styles.plus, pressed && !sending && styles.pressed]}
        >
          {sending ? <ActivityIndicator color={colors.accent} /> : <Ionicons name="add" size={26} color={colors.textSub} />}
        </Pressable>
        <View style={styles.inputBox}>
          <TextInput
            ref={inputRef}
            style={[styles.input, { height: inputH }]}
            value={value}
            onChangeText={(t) => {
              setSel(null);
              onChangeText(t);
            }}
            selection={sel ?? undefined}
            onSelectionChange={() => setSel(null)}
            placeholder="메시지를 입력하세요"
            placeholderTextColor={colors.placeholder}
            multiline
            onContentSizeChange={Platform.OS === "web" ? undefined : (e) => setInputH(Math.min(MAX_H, Math.max(ROW_H, Math.ceil(e.nativeEvent.contentSize.height) + spacing.xs * 2)))}
            {...(Platform.OS === "web" ? { rows: 1 } : {})} // 웹의 여러 줄 입력칸은 기본 2줄 높이로 시작하므로 한 줄로 시작하게 한다
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
          else if (onShare && isPlusShare(key)) {
            handoff.current?.();
            // "+" 시트가 완전히 닫힌 뒤에 공유 시트(다른 창)를 연다. 겹쳐 뜨면 iOS 에서 열리지 않는 경우가 있다
            handoff.current = scheduleAfterSheetClose(() => onShare(plusShareKind(key)), { runAfterInteractions: (cb) => InteractionManager.runAfterInteractions(cb) });
          }
          else setSoon(true); // 안부의 실제 기능은 이후 작업: 지금은 안내만
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  hintBox: { marginHorizontal: spacing.sm, borderRadius: radius.md, backgroundColor: colors.surface, paddingTop: spacing.xs },
  hints: { maxHeight: 160 }, // 4줄 높이까지, 넘으면 스크롤
  hint: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 40, paddingHorizontal: spacing.md },
  chip: { minWidth: 64, alignItems: "center", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  chipText: { ...font.caption, color: colors.textSub },
  hintText: { ...font.caption, color: colors.text, flex: 1, minWidth: 0 },
  replyBar: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginHorizontal: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderLeftWidth: 3, borderLeftColor: colors.accent, borderRadius: radius.sm, backgroundColor: colors.surface },
  replyTexts: { flex: 1, minWidth: 0 },
  replyName: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub },
  replyLine: { ...font.caption, color: colors.text },
  wrap: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: colors.card,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
    gap: spacing.xs,
  },
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.xs },
  plus: { width: ROW_H, height: ROW_H, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  inputBox: { flex: 1, flexDirection: "row", alignItems: "flex-end", borderRadius: radius.card, backgroundColor: colors.surface },
  input: {
    flex: 1,
    minHeight: ROW_H,
    maxHeight: MAX_H,
    paddingLeft: spacing.lg,
    paddingRight: spacing.xs,
    paddingVertical: spacing.xs,
    // lineHeight 를 주면 안드로이드 입력칸의 글자·안내 문구가 위로 밀려 윗부분이 잘린다
    fontSize: font.body.fontSize,
    fontFamily: font.body.fontFamily,
    color: colors.text,
    textAlignVertical: "center",
    includeFontPadding: false, // 안드로이드 글자 위아래 기본 여백 제거
  },
  slot: { width: INNER_SLOT, height: ROW_H, flexDirection: "row", alignItems: "center", justifyContent: "flex-end", paddingRight: spacing.xs },
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
