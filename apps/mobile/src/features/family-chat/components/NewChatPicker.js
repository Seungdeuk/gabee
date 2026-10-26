import { Pressable, StyleSheet, Text, View } from "react-native";

import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 새 대화 상대 고르기: 나를 뺀 가족 구성원 목록. 누르면 그 사람과의 1:1 방을 열거나 만든다.
 * @param {{ members: { id: string, name: string, photoUrl: string | null }[], busyId: string | null, error: string, onPick: (id: string) => void }} props busyId 는 열고 있는 상대(중복 누름 방지)
 */
export default function NewChatPicker({ members, busyId, error, onPick }) {
  return (
    <View style={styles.card}>
      <Text style={styles.title} accessibilityRole="header">
        누구와 대화할까요?
      </Text>
      {members.length === 0 ? <Text style={styles.empty}>대화할 다른 가족이 아직 없어요</Text> : null}
      {members.map((m) => (
        <Pressable
          key={m.id}
          onPress={() => onPick(m.id)}
          disabled={busyId != null}
          accessibilityRole="button"
          accessibilityLabel={`${m.name}님과 1:1 대화 시작`}
          style={({ pressed }) => [styles.row, pressed && styles.pressed, busyId != null && busyId !== m.id && styles.dim]}
        >
          <UserAvatar name={m.name} userId={m.id} photoUrl={m.photoUrl} size={40} />
          <Text style={styles.name} numberOfLines={1}>
            {m.name}
          </Text>
          {busyId === m.id ? <Text style={styles.busy}>여는 중…</Text> : null}
        </Pressable>
      ))}
      {error ? (
        <Text style={styles.error} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.xs, padding: spacing.md, borderRadius: radius.card, borderWidth: 1, borderColor: colors.divider, backgroundColor: colors.card },
  title: { ...font.cardTitle, color: colors.text, paddingHorizontal: spacing.sm, paddingBottom: spacing.xs },
  empty: { ...font.caption, color: colors.textMuted, paddingHorizontal: spacing.sm, paddingBottom: spacing.sm },
  row: { minHeight: 56, flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.sm, borderRadius: radius.lg },
  pressed: { backgroundColor: colors.surface },
  dim: { opacity: 0.5 },
  name: { flex: 1, ...font.body, color: colors.text },
  busy: { ...font.caption, color: colors.textMuted },
  error: { ...font.caption, color: colors.danger, paddingHorizontal: spacing.sm, paddingTop: spacing.xs },
});
