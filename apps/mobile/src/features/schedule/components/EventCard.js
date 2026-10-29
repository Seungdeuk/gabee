import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { KIND_COLOR, TOPIC_TEXT } from "../constants";
import { topics } from "../mock";
import { isShared } from "../model";
import { formatClockRange } from "../utils/date";
import CheckMark from "./CheckMark";
import SharedTag from "./SharedTag";

/**
 * 한 줄 카드. 왼쪽 막대 색으로 형태를 구분하고, 제목 앞은 공동 이름표(공동 일정일 때만), 제목 뒤는 주제 글자.
 * 시간이 없거나 종일이면 시간 자리를 글자 없이 비운다.
 * - compact(메인): 시간은 오른쪽에 짧게(09:00–10:00).
 * - detailed(달력·목록): 시간과 장소를 제목 아래 한 줄로(09:00 – 10:00 · 시립병원).
 * past 는 지난 항목: 흐리게 보이고 확인·완료 체크가 없다.
 * @param {{ item: import("../model").ScheduleItem, variant?: "compact" | "detailed", past?: boolean, onPress?: () => void, onToggleCheck?: () => void }} props
 */
export default function EventCard({ item, variant = "compact", past = false, onPress, onToggleCheck }) {
  const detailed = variant === "detailed";
  const topic = topics.find((t) => t.id === item.topicId);
  const time = formatClockRange(item, detailed ? " – " : "–");
  const sub = detailed ? [time, item.place].filter(Boolean).join(" · ") : "";
  return (
    <Pressable
      onPress={onPress}
      style={[styles.card, detailed && styles.cardDetailed, past && styles.cardPast]}
      accessibilityRole="button"
    >
      <View style={[styles.bar, { backgroundColor: KIND_COLOR[item.kind] }]} />
      <View style={styles.main}>
        <View style={styles.titleRow}>
          {isShared(item) ? <SharedTag label="공동" /> : null}
          <Text style={[styles.title, past && styles.titlePast]}>
            {item.title}
            {topic ? <Text style={[styles.topic, { color: TOPIC_TEXT[topic.color] }]}>{`  ${topic.name}`}</Text> : null}
          </Text>
        </View>
        {sub ? <Text style={styles.sub}>{sub}</Text> : null}
      </View>
      {!detailed && time ? <Text style={styles.time}>{time}</Text> : null}
      {past ? null : (
        <CheckMark kind={item.kind} checked={item.checked} onPress={onToggleCheck} size={detailed ? 24 : 18} />
      )}
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
  cardDetailed: { gap: spacing.md, paddingVertical: spacing.md, paddingLeft: 14, paddingRight: spacing.lg },
  cardPast: { backgroundColor: "transparent", shadowOpacity: 0, elevation: 0 },
  titlePast: { color: colors.textMuted },
  bar: { width: 4, alignSelf: "stretch", borderRadius: 4 },
  main: { flex: 1, gap: 2 },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  title: { flexShrink: 1, fontSize: 16, color: colors.text },
  topic: { ...font.caption, fontWeight: "500" },
  sub: { ...font.caption, color: colors.textMuted },
  time: { fontSize: 12, color: colors.textMuted },
});
