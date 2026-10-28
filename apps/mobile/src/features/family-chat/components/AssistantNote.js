import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import ScheduleConfirmCard from "@/features/ai-assistant/components/ScheduleConfirmCard";
import { colors, font, radius, spacing } from "@/theme";

import { formatTime } from "../chatUtils";
import { ASSISTANT_NAME, privateNotice } from "../mention";
import AssistantAvatar from "./AssistantAvatar";

const AVATAR = 36;

/**
 * 가족 채팅방에서 @가비 로 부른 뒤 **나에게만 보이는** 가비의 말풍선(서버에 남지 않고 이 화면을 닫으면 사라진다).
 * - pending: 답을 기다리는 중
 * - private: 개인 정보가 있어서 방에 올리지 않은 답(이유 한 줄과 함께)
 * - info: 사용법 안내
 * - error: 답을 못 받음(다시 시도·닫기)
 * 일정 공유 등록·수정·삭제처럼 확인이 필요한 요청은 이 말풍선 안에 확인 카드로 나오고, 버튼을 눌러야 반영된다.
 * @param {{ note: object, onRetry?: (question: string) => void, onDismiss?: (id: string) => void, onResolveCard?: (noteId: string, index: number, status: string, text: string) => void }} props
 */
export default function AssistantNote({ note, onRetry, onDismiss, onResolveCard }) {
  const pending = note.state === "pending";
  const error = note.state === "error";
  const cards = note.confirmCards ?? [];
  return (
    <View style={styles.row} accessibilityLabel={`${ASSISTANT_NAME}, 나에게만 보이는 답`}>
      <AssistantAvatar size={AVATAR} />
      <View style={styles.column}>
        <Text style={styles.name}>{ASSISTANT_NAME} · 나에게만 보여요</Text>
        <View style={[styles.bubble, error && styles.errorBubble]}>
          {pending ? (
            <View style={styles.pending}>
              <ActivityIndicator color={colors.accent} size="small" accessibilityLabel="가비가 답하는 중" />
              <Text style={styles.text}>가비가 답하는 중…</Text>
            </View>
          ) : (
            <Text style={[styles.text, error && styles.errorText]} selectable>
              {note.text}
            </Text>
          )}
          {note.state === "private" ? <Text style={styles.notice}>{cards.length > 0 ? "확인이 필요한 요청이라 나에게만 보여요. 버튼을 눌러야 반영돼요." : privateNotice(note.reasons)}</Text> : null}
          {cards.map((card, i) => (
            <ScheduleConfirmCard key={`confirm-${i}`} card={card} onResolve={(status, text) => onResolveCard?.(note.id, i, status, text)} />
          ))}
          {error || note.state === "info" || note.state === "private" ? (
            <View style={styles.actions}>
              {error && note.question && onRetry ? (
                <Pressable onPress={() => onRetry(note.question)} accessibilityRole="button" accessibilityLabel="다시 시도" style={styles.action}>
                  <Text style={styles.actionText}>다시 시도</Text>
                </Pressable>
              ) : null}
              <Pressable onPress={() => onDismiss?.(note.id)} accessibilityRole="button" accessibilityLabel="닫기" style={styles.action}>
                <Text style={styles.dismissText}>닫기</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
        {pending ? null : <Text style={styles.time}>{formatTime(note.created_at)}</Text>}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: 2 },
  column: { flexShrink: 1, maxWidth: "80%", gap: spacing.xs, alignItems: "flex-start" },
  name: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub },
  bubble: { maxWidth: "100%", backgroundColor: colors.honeySoft, borderWidth: 1, borderStyle: "dashed", borderColor: colors.accent, borderRadius: radius.bubble, borderTopLeftRadius: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, gap: spacing.xs },
  errorBubble: { backgroundColor: colors.dangerSoft, borderColor: colors.danger },
  pending: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  text: { ...font.body, color: colors.text },
  errorText: { color: colors.danger },
  notice: { ...font.caption, color: colors.textMuted },
  actions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xs },
  action: { minHeight: 32, justifyContent: "center" },
  actionText: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.accent },
  dismissText: { ...font.caption, color: colors.textMuted },
  time: { ...font.tab, color: colors.textMuted },
});
