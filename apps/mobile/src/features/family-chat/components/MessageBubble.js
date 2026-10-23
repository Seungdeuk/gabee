import { Pressable, StyleSheet, Text, View } from "react-native";

import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, radius, spacing } from "@/theme";

import { formatTime } from "../chatUtils";
import { unreadByA11yLabel } from "../listUtils";

const AVATAR = 36;

/**
 * 말풍선 한 줄. 내 말은 오른쪽(복숭아색, 시각은 왼쪽 아래), 상대는 왼쪽(아바타·이름·카드색, 시각은 오른쪽 아래).
 * 내 말풍선은 아직 읽지 않은 사람이 있을 때만 시각 위에 작은 숫자(unread)를 보여 준다(모두 읽으면 표시 없음).
 * 전송 중이면 "전송 중…", 실패하면 "전송 실패 · 다시 보내기"(누르면 재전송, 길게 누르거나 "삭제" 로 지움).
 * @param {{ message: object, mine: boolean, showName: boolean, showTime?: boolean, unread?: number, photoUrl?: string | null, onRetry?: (clientId: string) => void, onDiscard?: (clientId: string) => void }} props
 */
export default function MessageBubble({ message, mine, showName, showTime = true, unread = 0, photoUrl, onRetry, onDiscard }) {
  const failed = message.status === "failed";
  const sending = message.status === "sending";

  const bubble = (
    <View style={[styles.bubble, mine ? styles.mineBubble : styles.otherBubble, sending && styles.dim]}>
      <Text style={styles.text} selectable>
        {message.text}
      </Text>
    </View>
  );

  let meta = null;
  if (failed) {
    meta = (
      <View style={styles.failRow}>
        <Pressable
          onPress={() => onRetry?.(message.clientId)}
          onLongPress={() => onDiscard?.(message.clientId)}
          accessibilityRole="button"
          accessibilityLabel="전송 실패. 다시 보내기. 길게 누르면 지워요"
          style={styles.failBox}
        >
          <Text style={styles.fail}>전송 실패 · 다시 보내기</Text>
        </Pressable>
        <Pressable onPress={() => onDiscard?.(message.clientId)} accessibilityRole="button" accessibilityLabel="보내지 못한 메시지 삭제" style={styles.failBox}>
          <Text style={styles.discard}>삭제</Text>
        </Pressable>
      </View>
    );
  } else if (sending) {
    meta = <Text style={styles.time}>전송 중…</Text>;
  } else if (showTime) {
    meta = <Text style={styles.time}>{formatTime(message.created_at)}</Text>;
  }

  const unreadNode =
    mine && !failed && !sending && unread > 0 ? (
      <Text style={styles.unread} accessibilityLabel={unreadByA11yLabel(unread)}>
        {unread}
      </Text>
    ) : null;

  if (mine) {
    return (
      <View style={[styles.row, styles.mineRow]}>
        {meta || unreadNode ? (
          <View style={styles.metaMine}>
            {unreadNode}
            {meta}
          </View>
        ) : null}
        {bubble}
      </View>
    );
  }
  return (
    <View style={styles.row}>
      {showName ? <UserAvatar name={message.user_name || "?"} userId={message.user_id} photoUrl={photoUrl} size={AVATAR} /> : <View style={styles.spacer} />}
      <View style={styles.column}>
        {showName ? <Text style={styles.name}>{message.user_name}</Text> : null}
        <View style={styles.line}>
          {bubble}
          {meta ? <View style={styles.metaOther}>{meta}</View> : null}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: 2 },
  mineRow: { justifyContent: "flex-end" },
  spacer: { width: AVATAR },
  column: { flexShrink: 1, gap: spacing.xs, alignItems: "flex-start" },
  line: { flexDirection: "row", alignItems: "flex-end", gap: spacing.xs, maxWidth: "100%" },
  name: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub },
  bubble: { flexShrink: 1, maxWidth: "70%", paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, borderRadius: radius.bubble },
  mineBubble: { backgroundColor: colors.peach, borderBottomRightRadius: spacing.xs },
  otherBubble: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderTopLeftRadius: spacing.xs },
  dim: { opacity: 0.6 },
  text: { ...font.body, color: colors.text, userSelect: "text" },
  time: { ...font.tab, color: colors.textMuted },
  unread: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.accent },
  metaMine: { alignItems: "flex-end", justifyContent: "flex-end", flexShrink: 0 },
  metaOther: { justifyContent: "flex-end", flexShrink: 0 },
  failRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  failBox: { minHeight: 32, justifyContent: "center" },
  fail: { ...font.tab, color: colors.danger },
  discard: { ...font.tab, color: colors.textMuted },
});
