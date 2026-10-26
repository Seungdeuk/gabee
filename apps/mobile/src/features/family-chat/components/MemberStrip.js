import { ScrollView, StyleSheet, Text, View } from "react-native";

import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, spacing } from "@/theme";

const AVATAR = 48;

/**
 * 구성원 아바타 가로 줄(사진 또는 이니셜 + 이름). 많으면 가로로 밀어서 본다.
 * @param {{ heading: string, members: { id: string, name: string, photoUrl: string | null }[] }} props drawerMembers 의 결과
 */
export default function MemberStrip({ heading, members }) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.heading} accessibilityRole="header">
        {heading}
      </Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.strip}>
        {members.map((m) => (
          <View key={m.id} style={styles.item} accessible accessibilityLabel={m.name}>
            <UserAvatar name={m.name} userId={m.id} photoUrl={m.photoUrl} size={AVATAR} />
            <Text style={styles.name} numberOfLines={1}>
              {m.name}
            </Text>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingTop: spacing.lg, paddingBottom: spacing.md },
  heading: { ...font.bodyStrong, color: colors.text, paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
  strip: { gap: spacing.md, paddingHorizontal: spacing.lg },
  item: { width: 60, alignItems: "center", gap: spacing.xs },
  name: { ...font.caption, color: colors.textSub, textAlign: "center", maxWidth: 60 },
});
