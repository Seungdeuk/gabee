import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 가비의 인사이트: 공유 데이터에서 바로 나오는 문장 목록. action 이 "schedule" 인 줄은 일정으로 가는 링크가 붙는다.
 * @param {{ insights: { key: string, text: string, action?: string }[], onOpenSchedule: () => void }} props
 * @returns {import("react").ReactElement}
 */
export default function InsightCard({ insights, onOpenSchedule }) {
  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Text style={styles.label}>가비의 인사이트</Text>
        <Text style={styles.source}>공유 데이터 기준</Text>
      </View>
      {insights.map((item) => (
        <View key={item.key} style={styles.item}>
          <View style={styles.line}>
            <View style={styles.dot} />
            <Text style={styles.text}>{item.text}</Text>
          </View>
          {item.action === "schedule" ? (
            <Pressable
              style={styles.link}
              onPress={onOpenSchedule}
              accessibilityRole="link"
              accessibilityLabel="일정에서 확인하기"
            >
              <Text style={styles.linkText}>일정에서 확인하기</Text>
              <Ionicons name="chevron-forward" size={14} color={colors.accent} />
            </Pressable>
          ) : null}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md, padding: spacing.lg, borderRadius: radius.card, backgroundColor: colors.honeySoft },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  label: { ...font.caption, color: colors.accent, fontFamily: font.bodyStrong.fontFamily },
  source: { ...font.tab, color: colors.textMuted },
  item: { gap: spacing.xs },
  line: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  dot: { width: 6, height: 6, marginTop: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.accent },
  text: { ...font.body, flex: 1, color: colors.text },
  link: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", minHeight: 44, marginLeft: spacing.lg },
  linkText: { ...font.caption, color: colors.accent, fontFamily: font.bodyStrong.fontFamily },
});
