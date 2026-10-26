import { Pressable, StyleSheet, Text, View } from "react-native";

import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 가족 연락처 한 줄: 사진, 이름(별명이 있으면 별명이 크고 본래 이름이 작게), 관계, 메모 한 줄, 오른쪽 "대화하기".
 * 나 자신 줄에는 대화하기·별명 버튼이 없다.
 * @param {{ canEdit: boolean, row: { id: string, title: string, subtitle: string, relation: string, memo: string, photoUrl: string | null, isMe: boolean }, busy: boolean, onTalk: () => void, onEdit: () => void }} props busy 는 이 줄의 1:1 방을 여는 중
 */
export default function ContactRow({ row, canEdit, busy, onTalk, onEdit }) {
  const sub = [row.isMe ? "나" : null, row.subtitle, row.relation].filter(Boolean).join(" · ");
  return (
    <View style={styles.row}>
      <Pressable
        onPress={row.isMe || !canEdit ? undefined : onEdit}
        disabled={row.isMe || !canEdit}
        accessibilityRole="button"
        accessibilityLabel={row.isMe ? `${row.title}, 나` : `${row.title} 별명·메모 고치기`}
        style={({ pressed }) => [styles.main, pressed && !row.isMe && canEdit && styles.pressed]}
      >
        <UserAvatar name={row.realName ?? row.title} userId={row.id} photoUrl={row.photoUrl} size={44} />
        <View style={styles.text}>
          <Text style={styles.name} numberOfLines={1}>
            {row.title}
          </Text>
          {sub ? (
            <Text style={styles.sub} numberOfLines={1}>
              {sub}
            </Text>
          ) : null}
          {row.memo ? (
            <Text style={styles.memo} numberOfLines={1}>
              {row.memo}
            </Text>
          ) : null}
        </View>
      </Pressable>
      {row.isMe ? null : (
        <Pressable onPress={onTalk} disabled={busy} accessibilityRole="button" accessibilityLabel={`${row.title}님과 1:1 대화하기`} style={[styles.talk, busy && styles.dim]}>
          <Text style={styles.talkText}>{busy ? "여는 중…" : "대화하기"}</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  main: { flex: 1, minHeight: 56, flexDirection: "row", alignItems: "center", gap: spacing.md, borderRadius: radius.md },
  pressed: { backgroundColor: colors.surface },
  text: { flex: 1, gap: 2 },
  name: { ...font.bodyStrong, color: colors.text },
  sub: { ...font.caption, color: colors.textMuted },
  memo: { ...font.caption, color: colors.textSub },
  talk: { minHeight: 40, justifyContent: "center", paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.peach },
  talkText: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  dim: { opacity: 0.5 },
});
