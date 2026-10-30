import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, spacing } from "@/theme";

const AVATAR = 36;

/**
 * 구성원 드롭다운. 맨 위 줄("가족 구성원 N명")을 누르면 사진(또는 이니셜) + 이름 목록이 펼쳐지고 다시 누르면 접힌다. 처음에는 접혀 있다.
 * @param {{ heading: string, members: { id: string, name: string, photoUrl: string | null }[] }} props drawerMembers 의 결과
 */
export default function MemberStrip({ heading, members }) {
  const [open, setOpen] = useState(false);
  return (
    <View style={styles.wrap}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        accessibilityRole="button"
        accessibilityLabel={heading}
        accessibilityState={{ expanded: open }}
        accessibilityHint={open ? "누르면 구성원 목록을 접어요" : "누르면 구성원 목록을 펼쳐요"}
        style={styles.head}
      >
        <Text style={styles.heading}>{heading}</Text>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={20} color={colors.textSub} />
      </Pressable>
      {open
        ? members.map((m) => (
            <View key={m.id} style={styles.item} accessible accessibilityLabel={m.name}>
              <UserAvatar name={m.name} userId={m.id} photoUrl={m.photoUrl} size={AVATAR} />
              <Text style={styles.name} numberOfLines={1}>
                {m.name}
              </Text>
            </View>
          ))
        : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingTop: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 48, paddingHorizontal: spacing.lg },
  heading: { ...font.bodyStrong, color: colors.text },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.xs },
  name: { ...font.body, color: colors.text, flex: 1 },
});
