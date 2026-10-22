import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

/**
 * 일정 페이지 맨 아래 채팅 입력. 왼쪽 웃는 얼굴(크림 원), 오른쪽 복숭아 엔터 버튼.
 * @param {{ onSubmit?: (text: string) => void }} props 보내면 입력창을 비운다 (답변 시트는 채팅 화면에서 연결)
 */
export default function ChatInputBar({ onSubmit }) {
  const [text, setText] = useState("");
  const send = () => {
    const value = text.trim();
    if (!value) return;
    onSubmit?.(value);
    setText("");
  };
  return (
    <View style={styles.bar}>
      <View style={styles.face}>
        <Ionicons name="happy-outline" size={22} color={colors.text} />
      </View>
      <TextInput
        value={text}
        onChangeText={setText}
        onSubmitEditing={send}
        placeholder="일정에 대해 물어보세요"
        placeholderTextColor={colors.textMuted}
        returnKeyType="send"
        style={styles.input}
      />
      <Pressable onPress={send} accessibilityRole="button" accessibilityLabel="보내기" style={styles.send}>
        <Ionicons name="return-down-back" size={22} color={colors.text} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: spacing.sm,
    paddingLeft: spacing.md,
    paddingRight: spacing.sm,
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
  face: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceStrong,
  },
  input: { flex: 1, fontSize: 16, color: colors.text, paddingVertical: spacing.xs },
  send: {
    width: 40,
    height: 40,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.peach,
  },
});
