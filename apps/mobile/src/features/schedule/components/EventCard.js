import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { KIND_COLOR, TOPIC_TEXT } from "../constants";
import { members, topics } from "../mock";
import { whoLabels } from "../model";
import { formatClockRange } from "../utils/date";
import CheckMark from "./CheckMark";

/**
 * 한 줄 카드. 왼쪽 막대 색으로 형태를 구분하고, 제목 앞은 이름표(누구), 제목 뒤는 주제 글자,
 * 오른쪽은 시간(24시간)과 체크. 시간이 없거나 종일이면 시간 자리를 글자 없이 비운다.
 * @param {{ item: import("../model").ScheduleItem, onPress?: () => void, onToggleCheck?: () => void, showPlace?: boolean }} props
 */
export default function EventCard({ item, onPress, onToggleCheck, showPlace = false }) {
  const labels = whoLabels(item.whoIds, members);
  const topic = topics.find((t) => t.id === item.topicId);
  const time = formatClockRange(item);
  return (
    <Pressable onPress={onPress} style={styles.card} accessibilityRole="button">
      <View style={[styles.bar, { backgroundColor: KIND_COLOR[item.kind] }]} />
      <View style={styles.main}>
        <Text style={styles.title}>
          {labels.length > 0 ? <Text style={styles.who}>{` ${labels.join("·")} `}</Text> : null}
          {labels.length > 0 ? " " : null}
          {item.title}
          {topic ? <Text style={[styles.topic, { color: TOPIC_TEXT[topic.color] }]}>{`  ${topic.name}`}</Text> : null}
        </Text>
        {showPlace && item.place ? <Text style={styles.place}>{item.place}</Text> : null}
      </View>
      {time ? <Text style={styles.time}>{time}</Text> : null}
      <CheckMark kind={item.kind} checked={item.checked} onPress={onToggleCheck} />
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
  bar: { width: 4, alignSelf: "stretch", borderRadius: 4 },
  main: { flex: 1, gap: 2 },
  title: { fontSize: 16, color: colors.text },
  who: {
    ...font.caption,
    fontWeight: "500",
    color: colors.text,
    backgroundColor: colors.surfaceStrong,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  topic: { ...font.caption, fontWeight: "500" },
  place: { ...font.caption, color: colors.textMuted },
  time: { fontSize: 12, color: colors.textMuted },
});
