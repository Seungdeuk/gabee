import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 하단 메시지 입력창 (ChatGPT 스타일의 둥근 입력바).
 * @param {{ onSend: (text: string) => void, disabled?: boolean }} props
 */
export default function ChatInput({ onSend, disabled = false }) {
  const [text, setText] = useState("");
  const canSend = text.trim().length > 0 && !disabled;

  const handleSend = () => {
    if (!canSend) return;
    onSend(text);
    setText("");
  };

  return (
    <View style={styles.wrapper}>
      <View style={styles.bar}>
        <Pressable style={styles.plus} accessibilityLabel="첨부">
          <Ionicons name="add" size={24} color={colors.textSub} />
        </Pressable>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          placeholder="가비에게 물어보기"
          placeholderTextColor={colors.textMuted}
          multiline
          maxLength={2000}
        />
        <Pressable
          onPress={handleSend}
          disabled={!canSend}
          accessibilityLabel="보내기"
          style={[styles.send, canSend && styles.sendActive]}
        >
          <Ionicons name="arrow-up" size={20} color={canSend ? "#FFFFFF" : colors.textMuted} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12,
    backgroundColor: colors.background,
  },
  bar: {
    flexDirection: "row",
    alignItems: "flex-end",
    backgroundColor: colors.surfaceStrong,
    borderRadius: 26,
    paddingHorizontal: 6,
    paddingVertical: 6,
    gap: 4,
  },
  plus: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  input: {
    flex: 1,
    maxHeight: 120,
    minHeight: 40,
    paddingTop: 10,
    paddingBottom: 10,
    fontSize: 16,
    color: colors.text,
  },
  send: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.border,
  },
  sendActive: {
    backgroundColor: colors.primary,
  },
});
