import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius } from "@/theme";

import { KIND_COLOR } from "../constants";
import { members, topics } from "../mock";
import { whoLabels } from "../model";
import { formatTimeRange } from "../utils/date";
import CheckMark from "./CheckMark";

/**
 * 한 줄 카드. 막대 색으로 형태를 구분하고, 시간이 없거나 종일이면 시간 자리를 글자 없이 비운다.
 * 이름표(누구)는 제목 앞, 주제는 제목 뒤 칩.
 * @param {{ item: import("../model").ScheduleItem, onPress?: () => void, onToggleCheck?: () => void, showPlace?: boolean }} props
 */
export default function EventCard({ item, onPress, onToggleCheck, showPlace = false }) {
  const labels = whoLabels(item.whoIds, members);
  const topic = topics.find((t) => t.id === item.topicId);
  const time = item.allDay ? "" : formatTimeRange(item);
  const sub = [time, showPlace ? item.place : ""].filter(Boolean).join(" · ");
  return (
    <Pressable onPress={onPress} style={styles.card} accessibilityRole="button">
      <View style={[styles.bar, { backgroundColor: KIND_COLOR[item.kind] }]} />
      <View style={styles.main}>
        <Text style={[styles.title, item.checked && styles.done]} numberOfLines={1}>
          {labels.length > 0 ? <Text style={styles.who}>{labels.join("·")} </Text> : null}
          {item.title}
        </Text>
        {sub ? (
          <Text style={styles.sub} numberOfLines={1}>
            {sub}
          </Text>
        ) : null}
      </View>
      {topic ? <Text style={styles.topic}>{topic.name}</Text> : null}
      <CheckMark kind={item.kind} checked={item.checked} onPress={onToggleCheck} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 12,
    paddingRight: 14,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.divider,
    borderRadius: radius.lg,
    overflow: "hidden",
  },
  bar: { width: 5, alignSelf: "stretch" },
  main: { flex: 1, gap: 2 },
  title: { ...font.cardTitle, color: colors.text },
  done: { color: colors.textMuted, textDecorationLine: "line-through" },
  who: { color: colors.accent },
  sub: { ...font.caption, color: colors.textMuted },
  topic: {
    ...font.caption,
    fontWeight: "700",
    color: colors.textSub,
    backgroundColor: colors.honeySoft,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
    overflow: "hidden",
  },
});
