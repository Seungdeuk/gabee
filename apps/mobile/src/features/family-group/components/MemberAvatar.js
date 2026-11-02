import { Pressable, StyleSheet, Text, View } from "react-native";

import Tag from "@/shared/components/Tag";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, spacing } from "@/theme";

import { roleLabel } from "../messages";
import { relationText, shownName } from "../relations";

/**
 * 구성원 한 명의 프로필(사진·이름·관계). 소유자·관리자는 작은 권한 태그를 단다.
 * @param {{ member: { id: string, name: string, display_name?: string | null, role?: string, photo_url?: string | null, family_relation?: string | null, family_relation_detail?: string | null }, nickname?: { nickname?: string | null }, onPress?: (member: object) => void }} props
 * @returns {import("react").ReactElement}
 */
export default function MemberAvatar({ member, nickname, onPress }) {
  const name = shownName(member, nickname);
  const relation = relationText(member);
  const privileged = member.role === "owner" || member.role === "admin";
  return (
    <Pressable
      style={styles.item}
      onPress={() => onPress?.(member)}
      accessibilityRole="button"
      accessibilityLabel={`${name}, ${roleLabel(member.role)}`}
      testID={`member-${member.id}`}
    >
      <UserAvatar name={name} userId={member.id} photoUrl={member.photo_url} size={48} />
      <Text style={styles.name} numberOfLines={1}>{name}</Text>
      {relation ? <Text style={styles.relation} numberOfLines={1}>{relation}</Text> : null}
      {privileged ? <View style={styles.tag}><Tag label={roleLabel(member.role)} tone={member.role === "owner" ? "green" : "orange"} /></View> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  item: { width: 72, alignItems: "center", gap: spacing.xs },
  name: { ...font.bodyStrong, color: colors.text, maxWidth: 72 },
  relation: { ...font.caption, color: colors.textMuted, maxWidth: 72 },
  tag: { marginTop: 2 },
});
