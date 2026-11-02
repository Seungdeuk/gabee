import { ScrollView, StyleSheet, Text, View } from "react-native";

import Tag from "@/shared/components/Tag";
import { colors, font, spacing } from "@/theme";

import MemberAvatar from "./MemberAvatar";

/**
 * '우리 가족' 화면 맨 위: 가족 이름, 내 권한·구성원 수, 가로로 넘기는 구성원 프로필.
 * @param {{ name: string, memberCount: number, roleText: string, members: object[], nicknames?: Record<string, { nickname?: string | null }>, onPressMember?: (member: object) => void }} props
 * @returns {import("react").ReactElement}
 */
export default function FamilyHeader({ name, memberCount, roleText, members, nicknames = {}, isOwner = false, onPressMember }) {
  return (
    <View style={styles.wrap} testID="family-header">
      <Text style={styles.name} accessibilityRole="header">{name}</Text>
      <View style={styles.tags}>
        {roleText ? <Tag label={roleText} tone="green" /> : null}
        <Tag label={`구성원 ${memberCount}명`} />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {members.map((m) => (
          <MemberAvatar key={m.id} member={m} nickname={nicknames[m.id]} onPress={onPressMember} />
        ))}
      </ScrollView>
      <Text style={styles.hint}>{isOwner ? "구성원을 누르면 별명을 붙이거나 관리자를 지정할 수 있어요" : "구성원을 누르면 나만 보는 별명을 붙일 수 있어요"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.md },
  name: { ...font.page, color: colors.text },
  tags: { flexDirection: "row", gap: spacing.sm },
  row: { gap: spacing.md, paddingVertical: spacing.xs },
  hint: { ...font.caption, color: colors.textMuted },
});
