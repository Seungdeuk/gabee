import { Image } from "expo-image";
import { useRef } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

import mascot from "../../../../assets/images/gabee-mascot.png";
import { KIND_COLOR, TOPIC_TEXT } from "../constants";
import { members, topics } from "../mock";
import { whoLabels } from "../model";
import { useScheduleItems } from "../store";
import { addDays, formatSlashDate, fromDateKey, todayKey } from "../utils/date";

/** 미니 카드 오른쪽 글자. 예: "21일 09:00", 시간이 없으면 "21일", 종일이면 "21일 종일". */
function miniTime(item) {
  const day = `${fromDateKey(item.date).getDate()}일`;
  if (item.allDay) return `${day} 종일`;
  return item.startTime ? `${day} ${item.startTime}` : day;
}

/** 답 안의 약속·할 일 한 줄 카드. 왼쪽 막대 색은 형태, 이름표와 주제 글자를 붙이고 시간은 오른쪽. */
function MiniCard({ item, onPress }) {
  const labels = whoLabels(item.whoIds, members);
  const topic = topics.find((t) => t.id === item.topicId);
  return (
    <Pressable onPress={onPress} style={styles.mini} accessibilityRole="button">
      <View style={[styles.bar, { backgroundColor: KIND_COLOR[item.kind] }]} />
      <Text style={styles.miniTitle}>
        {labels.length > 0 ? <Text style={styles.tag}>{` ${labels.join("·")} `}</Text> : null}
        {labels.length > 0 ? " " : null}
        {item.title}
        {topic ? <Text style={[styles.topic, { color: TOPIC_TEXT[topic.color] }]}>{`  ${topic.name}`}</Text> : null}
      </Text>
      <Text style={styles.miniTime}>{miniTime(item)}</Text>
    </Pressable>
  );
}

/**
 * "추가해 드릴까요?" 제안 카드. 메인의 추천 카드와 같은 문장(날짜 이름 / 일정으로 추가해 드릴까요?)과 같은 버튼 규칙을 쓴다.
 * 이미 같은 일정이 있으면 버튼 대신 "추가했어요"를 보여 준다.
 */
function Suggestion({ message, added, onAdd, onLater }) {
  const { suggestion } = message;
  const date = addDays(todayKey(), suggestion.draft.daysFromToday);
  return (
    <View style={styles.sug}>
      <Text style={styles.sugText}>{`${formatSlashDate(date)} ${suggestion.name}`}</Text>
      <Text style={styles.sugSub}>일정으로 추가해 드릴까요?</Text>
      <View style={styles.sugButtons}>
        {added ? (
          <View style={[styles.btn, styles.btnOn]}>
            <Text style={[styles.btnText, styles.btnTextOn]}>추가했어요</Text>
          </View>
        ) : (
          <>
            <Pressable onPress={() => onAdd(suggestion, date)} style={styles.btn} accessibilityRole="button">
              <Text style={styles.btnText}>추가</Text>
            </Pressable>
            <Pressable
              onPress={() => onLater(message.id)}
              style={[styles.btn, message.later && styles.btnOn]}
              accessibilityRole="button"
              accessibilityState={{ selected: Boolean(message.later) }}
            >
              <Text style={[styles.btnText, message.later && styles.btnTextOn]}>나중에</Text>
            </Pressable>
          </>
        )}
      </View>
    </View>
  );
}

/**
 * 채팅 대화 목록. 사용자의 말은 크림색 말풍선(오른쪽), 가비의 답은 꿀벌 아바타 옆 흰 말풍선(왼쪽)이다.
 * 답은 문장 + 약속·할 일 미니 카드 + 추가 제안으로 이루어지고, 답을 쓰는 동안은 점 세 개, 답하지 못하면 "다시 시도"가 붙는다.
 * 새 말이 붙으면 맨 아래로 내려간다.
 * @param {{ messages: import("../chat").ChatMessage[], thinking: boolean, onRetry: () => void, onAdd: (suggestion: object, date: string) => void, onLater: (messageId: string) => void, onOpenItem: (id: string) => void, empty?: string }} props
 */
export default function ChatMessages({ messages, thinking, onRetry, onAdd, onLater, onOpenItem, empty }) {
  const items = useScheduleItems();
  const listRef = useRef(null);
  const isAdded = (suggestion, date) => items.some((item) => item.title === suggestion.draft.title && item.date === date);

  return (
    <ScrollView
      ref={listRef}
      style={styles.list}
      contentContainerStyle={styles.content}
      onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      {messages.length === 0 && !thinking ? <Text style={styles.empty}>{empty}</Text> : null}
      {messages.map((message) =>
        message.role === "user" ? (
          <View key={message.id} style={styles.me}>
            <Text style={styles.meText}>{message.text}</Text>
          </View>
        ) : (
          <View key={message.id} style={styles.ai}>
            <Image source={mascot} style={styles.avatar} contentFit="cover" />
            <View style={styles.bubble}>
              <Text style={styles.aiText}>{message.text}</Text>
              {message.items?.map((item) => (
                <MiniCard key={item.id} item={item} onPress={() => onOpenItem(item.id)} />
              ))}
              {message.suggestion ? (
                <>
                  <Suggestion
                    message={message}
                    added={isAdded(message.suggestion, addDays(todayKey(), message.suggestion.draft.daysFromToday))}
                    onAdd={onAdd}
                    onLater={onLater}
                  />
                  <Text style={styles.note}>추천은 참고용이에요. 내용을 확인 후 저장해 주세요 📝</Text>
                </>
              ) : null}
              {message.error ? (
                <Pressable onPress={onRetry} style={styles.retry} accessibilityRole="button">
                  <Text style={styles.btnText}>다시 시도</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ),
      )}
      {thinking ? (
        <View style={styles.ai}>
          <Image source={mascot} style={styles.avatar} contentFit="cover" />
          <View style={[styles.bubble, styles.dots]} accessibilityLabel="답을 쓰는 중">
            <View style={[styles.dot, { opacity: 0.5 }]} />
            <View style={[styles.dot, { opacity: 0.75 }]} />
            <View style={styles.dot} />
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  list: { flex: 1 },
  content: { gap: 10, paddingVertical: spacing.sm },
  empty: { fontSize: 15, color: colors.textMuted, textAlign: "center", paddingVertical: spacing.xxl },
  me: {
    alignSelf: "flex-end",
    maxWidth: "78%",
    backgroundColor: colors.surfaceStrong,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderBottomLeftRadius: 18,
    borderBottomRightRadius: 4,
    paddingVertical: 9,
    paddingHorizontal: 14,
  },
  meText: { fontSize: 15, lineHeight: 21, color: colors.text },
  ai: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  avatar: { width: 30, height: 30, borderRadius: 15, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.background },
  bubble: {
    flexShrink: 1,
    gap: 8,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderBottomLeftRadius: 4,
    borderBottomRightRadius: 18,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  aiText: { fontSize: 15, lineHeight: 22, color: colors.text },
  mini: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    paddingHorizontal: 12,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
  },
  bar: { width: 3, alignSelf: "stretch", borderRadius: 3 },
  miniTitle: { flex: 1, fontSize: 14, color: colors.text },
  tag: { fontSize: 12, fontWeight: "500", color: colors.text, backgroundColor: colors.surfaceStrong },
  topic: { fontSize: 12, fontWeight: "500" },
  miniTime: { fontSize: 12, color: colors.textMuted },
  sug: { gap: 2, backgroundColor: colors.surfaceStrong, borderRadius: 14, paddingTop: 10, paddingBottom: 8, paddingHorizontal: 12 },
  sugText: { fontSize: 15, lineHeight: 22, fontWeight: "500", color: colors.text },
  sugSub: { fontSize: 15, lineHeight: 22, color: colors.textMuted },
  sugButtons: { flexDirection: "row", justifyContent: "flex-end", gap: 6, marginTop: 6 },
  btn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 10,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  btnOn: { backgroundColor: colors.peach, borderColor: colors.peach },
  btnText: { fontSize: 13, fontWeight: "500", color: colors.text },
  btnTextOn: { fontWeight: "700" },
  retry: {
    alignSelf: "flex-start",
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 10,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  note: { fontSize: 12, color: colors.textMuted },
  dots: { flexDirection: "row", alignItems: "center", gap: 5, paddingVertical: 14 },
  dot: { width: 7, height: 7, borderRadius: radius.pill, backgroundColor: colors.textMuted },
});
