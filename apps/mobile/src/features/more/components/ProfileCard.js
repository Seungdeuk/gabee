import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, spacing } from "@/theme";

import { profileSubtitle } from "../menuItems";

/**
 * 마이 페이지 맨 위 프로필 카드: 로그인했으면 이름·가족/역할·내 정보 수정, 아니면 안내.
 * @param {{ user?: { id?: string, name?: string, photo_url?: string | null } | null, status: string, groupName?: string | null, roleText?: string | null, onEdit?: () => void, onLogin?: () => void }} props
 * @returns {import("react").ReactElement | null}
 */
export default function ProfileCard({ user, status, groupName, roleText, onEdit, onLogin }) {
  if (status === "loading") return null;
  if (status === "unreachable") {
    return (
      <Card tone="orange" testID="profile-card">
        <Text style={styles.title}>서버에 연결하지 못했어요</Text>
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
  return (
    <Card tone="white" testID="profile-card">
      <View style={styles.row}>
        <UserAvatar name={user?.name ?? "?"} userId={user?.id} photoUrl={user?.photo_url} size={64} />
        <View style={styles.info}>
          <Text style={styles.name}>{user?.name}</Text>
          <Text style={styles.sub}>{profileSubtitle(groupName, roleText)}</Text>
          <Pressable
            onPress={onEdit}
            accessibilityRole="button"
            accessibilityLabel="내 정보 수정"
            hitSlop={spacing.sm}
            style={({ pressed }) => [styles.edit, pressed && styles.pressed]}
          >
            <Text style={styles.editText}>내 정보 수정</Text>
            <Ionicons name="chevron-forward" size={14} color={colors.textMuted} />
          </Pressable>
        </View>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.cardTitle, color: colors.text },
  name: { ...font.section, color: colors.text },
  sub: { ...font.caption, color: colors.textMuted },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  info: { flex: 1, gap: spacing.xs },
  actions: { flexDirection: "row", gap: spacing.sm },
  edit: { flexDirection: "row", alignItems: "center", gap: spacing.xs, alignSelf: "flex-start" },
  editText: { ...font.caption, color: colors.textMuted },
  pressed: { opacity: 0.7 },
});
