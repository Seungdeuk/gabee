import { Pressable, StyleSheet, Text } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { replyLine } from "../messageActions";

/**
 * 말풍선 안 위쪽에 붙는 답장 원본 인용: 원본을 보낸 사람 이름과 한 줄 미리보기(글자 40자까지, 사진이면 "사진", 지웠으면 "삭제된 메시지입니다").
 * 누르면 원본 메시지로 이동한다(onPress 가 없으면 표시만).
 * 길게 누르면 말풍선과 같은 메뉴가 열리도록 onLongPress 를 받는다.
 * @param {{ reply: { id: number, user_name: string, text: string, deleted: boolean, has_attachment: boolean }, onPress?: (messageId: number) => void, onLongPress?: (event: object) => void }} props
 */
export default function ReplyQuote({ reply, onPress, onLongPress }) {
  const line = replyLine(reply);
  return (
    <Pressable
      onPress={onPress ? () => onPress(reply.id) : undefined}
      onLongPress={onLongPress}
      disabled={!onPress && !onLongPress}
      accessibilityRole="button"
      accessibilityLabel={`${reply.user_name}님의 메시지에 답장: ${line}. 누르면 원본으로 이동해요`}
      style={styles.box}
    >
      <Text style={styles.name} numberOfLines={1}>
        {reply.user_name}
      </Text>
      <Text style={[styles.line, reply.deleted && styles.gone]} numberOfLines={1}>
        {line}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  box: { marginBottom: spacing.xs, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderLeftWidth: 3, borderLeftColor: colors.accent, borderRadius: radius.sm, backgroundColor: colors.surface },
  name: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub },
  line: { ...font.caption, color: colors.text },
  gone: { color: colors.textMuted },
});
