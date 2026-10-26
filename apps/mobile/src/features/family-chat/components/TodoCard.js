import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 소통 탭의 "가족 할 일" 카드: 안 끝난 일 개수와 맨 앞 제목 미리보기. 누르면 할 일 화면으로 간다.
 * @param {{ preview: { count: number, titles: string[] }, onPress: () => void }} props
 */
export default function TodoCard({ preview, onPress }) {
  const { count, titles } = preview;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={count > 0 ? `가족 할 일, 남은 일 ${count}개` : "가족 할 일, 남은 일 없음"}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <View style={styles.text}>
        <Text style={styles.title}>
          가족 할 일 <Text style={styles.count}>{count > 0 ? `${count}개 남음` : "남은 일 없음"}</Text>
        </Text>
        {titles.map((t, i) => (
          <Text key={i} style={styles.item} numberOfLines={1}>
            {`• ${t}`}
          </Text>
        ))}
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.lg, borderWidth: 1, borderColor: colors.divider, borderRadius: radius.card, backgroundColor: colors.card },
  pressed: { backgroundColor: colors.surface },
  text: { flex: 1, gap: spacing.xs },
  title: { ...font.cardTitle, color: colors.text },
  count: { ...font.caption, color: colors.textMuted },
  item: { ...font.body, color: colors.textSub },
});
