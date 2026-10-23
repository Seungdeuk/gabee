import { Pressable, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import { colors, font, radius, spacing } from "@/theme";

import { formatTime, toneFor } from "../chatUtils";

const AVATAR = 36;

/**
 * 말풍선 한 줄. 내 말은 오른쪽(복숭아색), 상대는 왼쪽(아바타·이름·카드색).
 * 전송 중이면 "보내는 중…", 실패하면 "전송 실패 · 다시 보내기"(누르면 재전송, 길게 누르면 삭제).
 * @param {{ message: object, mine: boolean, showName: boolean, onRetry?: (clientId: string) => void, onDiscard?: (clientId: string) => void }} props
 */
export default function MessageBubble({ message, mine, showName, onRetry, onDiscard }) {
  const failed = message.status === "failed";
  const sending = message.status === "sending";
  const time = sending ? "보내는 중…" : formatTime(message.created_at);

  const bubble = (
    <View style={[styles.bubble, mine ? styles.mineBubble : styles.otherBubble, sending && styles.dim]}>
      <Text style={styles.text} selectable>
        {message.text}
      </Text>
    </View>
  );

  const meta = failed ? (
    <Pressable
      onPress={() => onRetry?.(message.clientId)}
      onLongPress={() => onDiscard?.(message.clientId)}
      accessibilityRole="button"
      accessibilityLabel="전송 실패. 다시 보내기. 길게 누르면 지워요"
      style={styles.failBox}
    >
      <Text style={styles.fail}>전송 실패 · 다시 보내기</Text>
    </Pressable>
  ) : (
    <Text style={styles.time}>{time}</Text>
  );

  if (mine) {
    return (
      <View style={[styles.row, styles.mineRow]}>
        <View style={styles.metaMine}>{meta}</View>
        {bubble}
      </View>
    );
  }
  return (
    <View style={styles.row}>
      {showName ? <Avatar name={message.user_name || "?"} tone={toneFor(message.user_id)} size={AVATAR} /> : <View style={styles.spacer} />}
      <View style={styles.column}>
        {showName ? <Text style={styles.name}>{message.user_name}</Text> : null}
        <View style={styles.line}>
          {bubble}
          <View style={styles.metaOther}>{meta}</View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: 2 },
  mineRow: { justifyContent: "flex-end" },
  spacer: { width: AVATAR },
  column: { flexShrink: 1, gap: spacing.xs, alignItems: "flex-start" },
  line: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, maxWidth: "100%" },
  name: { ...font.caption, color: colors.textSub },
  bubble: { flexShrink: 1, maxWidth: "78%", paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, borderRadius: radius.bubble },
  mineBubble: { backgroundColor: colors.peach },
  otherBubble: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  dim: { opacity: 0.6 },
  text: { ...font.body, color: colors.text },
  time: { ...font.tab, color: colors.textMuted },
  metaMine: { alignItems: "flex-end", justifyContent: "flex-end" },
  metaOther: { justifyContent: "flex-end" },
  failBox: { minHeight: 32, justifyContent: "center" },
  fail: { ...font.tab, color: colors.danger },
});
