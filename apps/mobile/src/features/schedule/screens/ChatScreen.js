import { useRouter } from "expo-router";
import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import Logo from "@/shared/components/Logo";
import { colors, spacing } from "@/theme";

import { QUICK_QUESTIONS } from "../agent";
import { confirmAction, newChat, retryLast, sendMessage, toggleSuggestionLater, useChat } from "../chat";
import ChatInputBar from "../components/ChatInputBar";
import ChatMessages from "../components/ChatMessages";
import QuickChips from "../components/QuickChips";

/**
 * 채팅 전용 화면. 머리줄은 ‹ + 글자 로고 + [새 채팅] [기록], 아래로 대화, 입력창 위에 빠른 질문 칩 한 줄.
 * 메인의 하단 시트에서 "전체 화면"을 누르거나 기록에서 대화를 열면 여기로 오고 대화는 그대로 이어진다.
 * 제안 카드의 "추가"는 제안한 형태로 미리 채운 등록 화면을 열고, 저장하면 여기로 돌아온다.
 */
export default function ChatScreen() {
  const router = useRouter();
  const { messages, thinking } = useChat();

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/schedule"));
  const addSuggestion = (suggestion, date) =>
    router.push({ pathname: "/schedule/register", params: { kind: suggestion.draft.kind, title: suggestion.draft.title, date, suggested: "1" } });

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.body}>
        <View style={styles.top}>
          <View style={styles.titleBox}>
            <IconButton name="chevron-back" label="뒤로" onPress={leave} />
            <Logo size={21} />
          </View>
          <View style={styles.actions}>
            <Pressable onPress={newChat} style={[styles.pill, styles.pillMain]} accessibilityRole="button">
              <Text style={[styles.pillText, styles.pillTextMain]}>새 채팅</Text>
            </Pressable>
            <Pressable onPress={() => router.push("/schedule/chat-history")} style={styles.pill} accessibilityRole="button">
              <Text style={styles.pillText}>기록</Text>
            </Pressable>
          </View>
        </View>

        <ChatMessages
          messages={messages}
          thinking={thinking}
          onRetry={retryLast}
          onAdd={addSuggestion}
          onLater={toggleSuggestionLater}
          onConfirm={confirmAction}
          onOpenItem={(id) => router.push({ pathname: "/schedule/detail", params: { id } })}
          empty="일정에 대해 무엇이든 물어보세요"
        />
        <QuickChips questions={QUICK_QUESTIONS} onPress={sendMessage} />
        <ChatInputBar onSubmit={sendMessage} />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  body: { flex: 1, gap: spacing.md, paddingHorizontal: spacing.xxl, paddingTop: spacing.sm, paddingBottom: spacing.md },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  titleBox: { flexDirection: "row", alignItems: "center", marginLeft: -spacing.md },
  actions: { flexDirection: "row", gap: 6 },
  pill: {
    paddingVertical: 6,
    paddingHorizontal: 13,
    borderRadius: 999,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  pillMain: { backgroundColor: colors.peach, borderColor: colors.peach },
  pillText: { fontSize: 14, fontWeight: "500", color: colors.text },
  pillTextMain: { fontWeight: "700" },
});
