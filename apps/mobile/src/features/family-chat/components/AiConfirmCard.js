import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { blockedWarning, canSendToAi, INSUFFICIENT_WARNING, maskedChips, PREVIEW_ACTIONS, previewLineText, sendBlockReason } from "../privacyPreview";

/**
 * "AI에 보내기 전 확인" 카드. 가려지는 정보·제외되는 메시지를 보여 주고, 사용자가 "AI에 보내기"를 눌러야만 onConfirm 이 불린다.
 * @param {{
 *   action: "analysis" | "replies" | "topics",
 *   status: "loading" | "ready" | "error",
 *   preview: object | null,
 *   error: string,
 *   onConfirm: () => void,
 *   onCancel: () => void,
 *   onRetry: () => void,
 * }} props preview 는 parsePreview 결과
 * @returns {JSX.Element}
 */
export default function AiConfirmCard({ action, status, preview, error, onConfirm, onCancel, onRetry }) {
  const [open, setOpen] = useState(false);
  const warning = preview ? blockedWarning(preview.blockedMessages) : "";
  const blockReason = preview ? sendBlockReason(preview) : "";
  const chips = preview ? maskedChips(preview.masked) : [];

  return (
    <View style={styles.card} testID="chat-ai-confirm">
      <Text style={styles.title} accessibilityRole="header">
        이 내용이 AI로 전송돼요
      </Text>
      <Text style={styles.caption}>{PREVIEW_ACTIONS[action] ?? ""}</Text>
      <Text style={styles.sub}>전송은 지금 누르는 요청에서만 일어나요. 아래처럼 개인정보를 가려서 보내요. 가려진 값은 AI에게 가지 않아요.</Text>

      {status === "loading" ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.caption}>보낼 내용을 확인하는 중이에요...</Text>
        </View>
      ) : null}

      {status === "error" ? (
        <>
          <Text style={styles.error} accessibilityRole="alert">
            {error}
          </Text>
          <View style={styles.row}>
            <Button label="다시 시도" small variant="secondary" onPress={onRetry} testID="chat-ai-confirm-retry" />
            <Button label="취소" small variant="secondary" onPress={onCancel} testID="chat-ai-confirm-cancel" />
          </View>
        </>
      ) : null}

      {status === "ready" && preview ? (
        <>
          <Text style={styles.caption}>{`대화 ${preview.messageCount}개`}</Text>
          {chips.length > 0 ? (
            <View style={styles.chips}>
              {chips.map((chip) => (
                <View key={chip} style={styles.chip}>
                  <Text style={styles.chipText}>{chip}</Text>
                </View>
              ))}
            </View>
          ) : (
            <Text style={styles.caption}>가릴 개인정보가 없어요</Text>
          )}
          {warning ? (
            <Text style={styles.warning} accessibilityRole="alert" testID="chat-ai-confirm-blocked">
              {warning}
            </Text>
          ) : null}
          {blockReason === "disabled" ? (
            <Text style={styles.warning} accessibilityRole="alert" testID="chat-ai-confirm-disabled">
              AI 기능이 꺼져 있어요. 가족 소유자나 관리자가 켜야 보낼 수 있어요
            </Text>
          ) : null}
          {blockReason === "insufficient" ? (
            <Text style={styles.warning} accessibilityRole="alert" testID="chat-ai-confirm-insufficient">
              {INSUFFICIENT_WARNING}
            </Text>
          ) : null}

          <Pressable
            onPress={() => setOpen((v) => !v)}
            accessibilityRole="button"
            accessibilityState={{ expanded: open }}
            accessibilityLabel={open ? "보낼 내용 접기" : "보낼 내용 보기"}
            testID="chat-ai-confirm-toggle"
          >
            <Text style={styles.link}>{open ? "보낼 내용 접기" : "보낼 내용 보기"}</Text>
          </Pressable>
          {open ? (
            <View style={styles.lines} testID="chat-ai-confirm-lines">
              {preview.lines.map((line) => (
                <Text key={line.id} style={line.blocked ? styles.lineBlocked : styles.line}>
                  {previewLineText(line)}
                </Text>
              ))}
            </View>
          ) : null}

          <View style={styles.row}>
            <Button label="AI에 보내기" small onPress={onConfirm} disabled={!canSendToAi(preview)} testID="chat-ai-confirm-send" />
            <Button label="취소" small variant="secondary" onPress={onCancel} testID="chat-ai-confirm-cancel" />
          </View>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.xs, backgroundColor: colors.honeySoft, borderRadius: radius.md, padding: spacing.md },
  title: { ...font.cardTitle, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  caption: { ...font.caption, color: colors.textMuted },
  error: { ...font.body, color: colors.danger },
  warning: { ...font.caption, color: colors.warning, backgroundColor: colors.warningSoft, borderRadius: radius.sm, padding: spacing.sm },
  link: { ...font.bodyStrong, color: colors.accent },
  loading: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  chip: { backgroundColor: colors.card, borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  chipText: { ...font.caption, color: colors.text },
  lines: { gap: spacing.xs, backgroundColor: colors.card, borderRadius: radius.sm, padding: spacing.sm },
  line: { ...font.caption, color: colors.text },
  lineBlocked: { ...font.caption, color: colors.textMuted },
});
