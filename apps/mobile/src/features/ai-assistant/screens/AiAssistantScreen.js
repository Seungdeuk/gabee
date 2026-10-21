import { useEffect, useRef } from "react";
import { FlatList, KeyboardAvoidingView, Platform, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import ScreenHeader from "@/shared/components/ScreenHeader";
import { colors } from "@/theme";

import ChatInput from "../components/ChatInput";
import EmptyState from "../components/EmptyState";
import MessageBubble from "../components/MessageBubble";
import useChat from "../hooks/useChat";

/** 홈 화면: ChatGPT 모바일처럼 대화 중심으로 구성한 AI 비서 화면. */
export default function AiAssistantScreen() {
  const { messages, isTyping, send, reset } = useChat();
  const listRef = useRef(null);

  useEffect(() => {
    if (messages.length > 0) {
      listRef.current?.scrollToEnd({ animated: true });
    }
  }, [messages, isTyping]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScreenHeader
        title="가비"
        left={<IconButton name="menu-outline" label="메뉴" />}
        right={<IconButton name="create-outline" label="새 대화" onPress={reset} />}
      />

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={0}
      >
        {messages.length === 0 ? (
          <EmptyState onPick={send} />
        ) : (
          <FlatList
            ref={listRef}
            data={messages}
            keyExtractor={(item) => item.id}
            renderItem={({ item }) => <MessageBubble role={item.role} text={item.text} />}
            contentContainerStyle={styles.list}
            ItemSeparatorComponent={() => <View style={styles.gap} />}
            ListFooterComponent={isTyping ? <Text style={styles.typing}>가비가 답변을 쓰는 중…</Text> : null}
            keyboardShouldPersistTaps="handled"
          />
        )}
        <ChatInput onSend={send} disabled={isTyping} />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  flex: {
    flex: 1,
  },
  list: {
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 16,
  },
  gap: {
    height: 20,
  },
  typing: {
    marginTop: 16,
    marginLeft: 38,
    fontSize: 14,
    color: colors.textMuted,
  },
});
