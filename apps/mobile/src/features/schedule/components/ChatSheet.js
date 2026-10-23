import { useEffect, useRef, useState } from "react";
import { Animated, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, View } from "react-native";

import Logo from "@/shared/components/Logo";
import { colors, spacing } from "@/theme";

import { retryLast, sendMessage, toggleSuggestionLater, useChat } from "../chat";
import ChatInputBar from "./ChatInputBar";
import ChatMessages from "./ChatMessages";

const SHEET_OFFSET = 700;

/**
 * 메인에서 질문을 보내면 아래에서 올라오는 채팅 시트. 뒤의 메인은 흐리게 보이고, 하단 탭 바는 그대로 남는다.
 * 머리줄은 글자 로고 + [전체 화면] [닫기]. 닫아도 대화는 사라지지 않고, 다시 질문하면 같은 대화로 이어진다.
 * @param {{ visible: boolean, onClose: () => void, onFull: () => void, onAdd: (suggestion: object, date: string) => void, onOpenItem: (id: string) => void }} props
 */
export default function ChatSheet({ visible, onClose, onFull, onAdd, onOpenItem }) {
  const { messages, thinking } = useChat();
  const slide = useRef(new Animated.Value(0)).current;
  const [mounted, setMounted] = useState(visible);

  useEffect(() => {
    if (visible) {
      setMounted(true);
      Animated.timing(slide, { toValue: 1, duration: 220, useNativeDriver: true }).start();
    } else {
      Animated.timing(slide, { toValue: 0, duration: 180, useNativeDriver: true }).start(({ finished }) => {
        if (finished) setMounted(false);
      });
    }
  }, [visible, slide]);

  if (!mounted) return null;
  return (
    <View style={StyleSheet.absoluteFill}>
      <Animated.View style={[styles.backdrop, { opacity: slide }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="채팅 닫기" />
      </Animated.View>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.avoid}
        pointerEvents="box-none"
      >
        <Animated.View
          style={[styles.sheet, { transform: [{ translateY: slide.interpolate({ inputRange: [0, 1], outputRange: [SHEET_OFFSET, 0] }) }] }]}
        >
          <View style={styles.handle} />
          <View style={styles.head}>
            <Logo size={21} />
            <View style={styles.actions}>
              <Pressable onPress={onFull} style={styles.pill} accessibilityRole="button">
                <Text style={styles.pillText}>전체 화면</Text>
              </Pressable>
              <Pressable onPress={onClose} style={styles.pill} accessibilityRole="button">
                <Text style={styles.pillText}>닫기</Text>
              </Pressable>
            </View>
          </View>
          <ChatMessages
            messages={messages}
            thinking={thinking}
            onRetry={retryLast}
            onAdd={onAdd}
            onLater={toggleSuggestionLater}
            onOpenItem={onOpenItem}
            empty="일정에 대해 무엇이든 물어보세요"
          />
          <ChatInputBar onSubmit={sendMessage} />
        </Animated.View>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(85,59,41,0.35)" },
  avoid: { flex: 1, justifyContent: "flex-end" },
  sheet: {
    height: "78%",
    gap: spacing.md,
    paddingHorizontal: spacing.xxl,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    backgroundColor: colors.background,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
  },
  handle: { alignSelf: "center", width: 38, height: 4, borderRadius: 2, backgroundColor: colors.border },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  actions: { flexDirection: "row", gap: 6 },
  pill: {
    paddingVertical: 6,
    paddingHorizontal: 13,
    borderRadius: 999,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  pillText: { fontSize: 14, fontWeight: "500", color: colors.text },
});
