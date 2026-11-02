import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, spacing } from "@/theme";

import { profileSubtitle } from "../menuItems";

/**
 * 마이 페이지 맨 위 프로필 카드: 로그인했으면 이름·가족/역할·내 정보 수정, 아니면 안내.
 * @param {{ user?: { id?: string, name?: string, photo_url?: string | null } | null, status: string, displayName?: string | null, photoUrl?: string | null, groupName?: string | null, roleText?: string | null, onEdit?: () => void, onLogin?: () => void, onRetry?: () => void }} props
 * @returns {import("react").ReactElement | null}
 */
export default function ProfileCard({ user, status, displayName, photoUrl, groupName, roleText, onEdit, onLogin, onRetry }) {
  if (status === "loading") return <Card tone="white" testID="profile-card" style={styles.placeholder} />; // 불러오는 동안에도 자리를 잡아 아래 화면이 내려가지 않게 한다
  if (status === "unreachable") {
    return (
      <Card tone="orange" testID="profile-card">
        <Text style={styles.title}>서버에 연결하지 못했어요</Text>
        <Text style={styles.sub}>로그인 정보는 이 기기에 그대로 있어요.</Text>
        {onRetry ? <Button label="다시 시도" small variant="secondary" onPress={onRetry} /> : null}
      </Card>
    );
  }
  if (status !== "authenticated") {
    return (
      <Card tone="white" testID="profile-card">
        <Text style={styles.title}>로그인하지 않았어요</Text>
        <Text style={styles.sub}>계정을 만들면 다른 기기에서도 가족 그룹을 이어서 쓸 수 있어요.</Text>
        <View style={styles.actions}>
          <Button label="로그인" small onPress={onLogin} />
        </View>
      </Card>
    );
  }
  const name = displayName || user?.name || "";
  return (
    <Card tone="white" testID="profile-card" style={styles.compact}>
      <View style={styles.row}>
        <UserAvatar name={name || "?"} userId={user?.id} photoUrl={photoUrl ?? user?.photo_url} size={48} />
        <View style={styles.info}>
          <Text style={styles.name}>{name}</Text>
          <Text style={styles.sub}>{profileSubtitle(groupName, roleText)}</Text>
          {onEdit ? (
            <Pressable
              onPress={onEdit}
              accessibilityRole="button"
              accessibilityLabel="내 정보 수정"
              hitSlop={spacing.md}
              style={({ pressed }) => [styles.edit, pressed && styles.pressed]}
            >
              <Text style={styles.editText}>내 정보 수정</Text>
              <Ionicons name="chevron-forward" size={14} color={colors.textMuted} />
            </Pressable>
          ) : null}
        </View>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.cardTitle, color: colors.text },
  name: { ...font.cardTitle, color: colors.text },
  sub: { ...font.caption, color: colors.textMuted },
  compact: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  info: { flex: 1, gap: 2 },
  actions: { flexDirection: "row", gap: spacing.sm },
  edit: { flexDirection: "row", alignItems: "center", gap: spacing.xs, alignSelf: "flex-start" },
  editText: { ...font.caption, color: colors.textMuted },
  pressed: { opacity: 0.7 },
  placeholder: { minHeight: 72 },
});
