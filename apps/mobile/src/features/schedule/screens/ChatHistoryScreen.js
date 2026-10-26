import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { newChat, openConversation, useConversations } from "../chat";
import { formatChatTime, toDateKey, todayKey } from "../utils/date";

/** 지난 구역에서 먼저 보이는 개수. 나머지는 "이전 기록 더 보기". */
const PAST_PREVIEW = 3;

/**
 * 채팅 기록. "+ 새 채팅" 버튼, 구역은 "오늘"과 "지난"(숫자 없이 최근 몇 개 + 이전 기록 더 보기).
 * 대화를 누르면 그 대화를 열어 채팅 화면에서 이어서 대화한다. 새 채팅은 지금 대화를 기록에 남기고 빈 대화로 돌아간다.
 */
export default function ChatHistoryScreen() {
  const router = useRouter();
  const conversations = useConversations();
  const [morePast, setMorePast] = useState(false);

  const today = todayKey();
  const todays = conversations.filter((c) => toDateKey(new Date(c.updatedAt)) === today);
  const past = conversations.filter((c) => toDateKey(new Date(c.updatedAt)) !== today);
  const pastShown = morePast ? past : past.slice(0, PAST_PREVIEW);

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/schedule/chat"));
  const open = (id) => {
    openConversation(id);
    leave();
  };
  const startNew = () => {
    newChat();
    leave();
  };

  const card = (c) => (
    <Pressable key={c.id} onPress={() => open(c.id)} style={styles.card} accessibilityRole="button">
      <Text style={styles.cardTitle} numberOfLines={1}>
        {c.messages.find((m) => m.role === "user")?.text ?? ""}
      </Text>
      <Text style={styles.cardSub}>{formatChatTime(c.updatedAt)}</Text>
    </Pressable>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.titleBox}>
            <IconButton name="chevron-back" label="뒤로" onPress={leave} />
            <Text style={styles.title} accessibilityRole="header">
              기록
            </Text>
          </View>

          <Pressable onPress={startNew} style={styles.newButton} accessibilityRole="button">
            <Text style={styles.newText}>+ 새 채팅</Text>
          </Pressable>

          {todays.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.heading}>오늘</Text>
              {todays.map(card)}
            </View>
          ) : null}

          {past.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.heading}>지난</Text>
              {pastShown.map(card)}
              {!morePast && past.length > PAST_PREVIEW ? (
                <Pressable onPress={() => setMorePast(true)} style={styles.more} accessibilityRole="button">
                  <Text style={styles.moreText}>이전 기록 더 보기</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}

          {conversations.length === 0 ? <Text style={styles.empty}>아직 나눈 대화가 없어요</Text> : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 18 },
  titleBox: { flexDirection: "row", alignItems: "center", marginLeft: -spacing.md },
  title: { ...font.page, color: colors.text },
  newButton: { minHeight: 52, alignItems: "center", justifyContent: "center", borderRadius: radius.button, backgroundColor: colors.peach },
  newText: { fontSize: 16, fontWeight: "700", color: colors.text },
  section: { gap: spacing.md },
  heading: { ...font.title, color: colors.text },
  empty: { ...font.body, color: colors.textMuted },
  card: {
    gap: 2,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
  },
  cardTitle: { fontSize: 16, color: colors.text },
  cardSub: { ...font.caption, color: colors.textMuted },
  more: {
    alignItems: "center",
    paddingVertical: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.button,
  },
  moreText: { fontSize: 14, fontWeight: "500", color: colors.textMuted },
});
