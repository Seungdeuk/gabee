import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { REQUEST_COLOR } from "../constants";
import { acceptSummary } from "../request_view";
import { formatClockRange } from "../utils/date";

/**
 * 일정 메인 브리핑의 부탁 카드(내가 보낸 부탁). 일정 카드와 같은 테두리·그림자에 왼쪽 막대는 금색, 제목 앞에 "함께" 태그를 달고,
 * 체크 표시 대신 오른쪽에 수락 현황 배지를 보인다(전원 수락이면 초록). 사람 이름은 보이지 않는다.
 * @param {{ request: import("../model").TogetherRequest, onPress?: () => void }} props
 */
export default function RequestCard({ request, onPress }) {
  const time = formatClockRange(request, "–");
  const { label, full } = acceptSummary(request);
  return (
    <Pressable onPress={onPress} style={styles.card} accessibilityRole="button" accessibilityLabel={`함께 ${request.title}, ${label}`}>
      <View style={styles.bar} />
      <View style={styles.titleRow}>
        <View style={styles.tag}>
          <Text style={styles.tagText}>함께</Text>
        </View>
        <Text style={styles.title}>{request.title}</Text>
      </View>
      {time ? <Text style={styles.time}>{time}</Text> : null}
      <Text style={[styles.badge, full && styles.badgeFull]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    minHeight: 52,
    paddingVertical: spacing.sm,
    paddingLeft: spacing.md,
    paddingRight: 14,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
    shadowColor: colors.text,
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  bar: { width: 4, alignSelf: "stretch", borderRadius: 4, backgroundColor: REQUEST_COLOR },
  titleRow: { flex: 1, flexDirection: "row", alignItems: "center", gap: 6 },
  tag: { paddingHorizontal: 8, borderRadius: radius.pill, borderWidth: 1, borderColor: REQUEST_COLOR },
  tagText: { ...font.caption, lineHeight: 18, fontWeight: "700", color: colors.text, includeFontPadding: false },
  title: { flexShrink: 1, fontSize: 16, color: colors.text },
  time: { fontSize: 12, color: colors.textMuted },
  badge: {
    ...font.caption,
    fontWeight: "700",
    paddingHorizontal: 9,
    paddingVertical: 2,
    borderRadius: radius.pill,
    overflow: "hidden",
    color: colors.text,
    backgroundColor: colors.surfaceStrong,
  },
  badgeFull: { color: colors.onDark, backgroundColor: colors.success },
});
