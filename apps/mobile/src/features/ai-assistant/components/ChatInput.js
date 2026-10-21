import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 하단 둥근 입력창.
 * - idle: 옅은 꿀색 바탕, 마이크(말로 묻기)와 음성 대화 버튼
 * - listening: 흰 바탕에 진한 테두리, 받아 적은 글자 옆에 복숭아색 보내기 버튼
 * - disabled: 가비가 답하는 동안 입력을 막는다
 *
 * TODO: 음성 인식은 폰 키보드의 받아쓰기를 쓴다. 앱 안에서 직접 인식하려면 음성 인식 모듈을 붙인다.
 *
 * @param {{ mode: "idle" | "listening" | "disabled", onSend: (text: string, options: { voice: boolean }) => void, onMic: () => void, onVoice?: () => void }} props
 */
export default function ChatInput({ mode, onSend, onMic, onVoice }) {
  const [text, setText] = useState("");
  const inputRef = useRef(null);
  const listening = mode === "listening";
  const disabled = mode === "disabled";
  const canSend = text.trim().length > 0 && !disabled;

  // 음성 입력으로 바뀌면 입력창에 커서를 둬서 폰 키보드의 받아쓰기를 바로 쓸 수 있게 한다
  useEffect(() => {
    if (!listening) return undefined;
    // 마이크 버튼을 누른 직후에는 버튼이 포커스를 가져가므로, 한 박자 뒤에 입력창으로 옮긴다
    const timer = setTimeout(() => inputRef.current?.focus(), 60);
    return () => clearTimeout(timer);
  }, [listening]);

  const submit = () => {
    if (!canSend) return;
    onSend(text, { voice: listening });
    setText("");
  };

  return (
    <View style={[styles.bar, listening && styles.barListening]}>
      <TextInput
        ref={inputRef}
        style={[styles.input, disabled && styles.inputDisabled]}
        value={text}
        onChangeText={setText}
        onSubmitEditing={submit}
        returnKeyType="send"
        editable={!disabled}
        placeholder={disabled ? "응답 중" : "여기에서 입력"}
        placeholderTextColor={colors.placeholder}
        accessibilityLabel="가비에게 묻기"
      />

      {listening ? (
        <Pressable onPress={submit} disabled={!canSend} accessibilityLabel="보내기" style={styles.hit}>
          <View style={[styles.send, !canSend && styles.sendOff]}>
            <Ionicons name="arrow-up" size={20} color={colors.text} />
          </View>
        </Pressable>
      ) : null}

      <Pressable onPress={onMic} disabled={disabled} accessibilityLabel={listening ? "음성 입력 끝내기" : "말로 묻기"} style={styles.hit}>
        <Ionicons name={listening ? "close" : "mic-outline"} size={22} color={disabled ? colors.disabled : listening ? colors.textMuted : colors.text} />
      </Pressable>

      {!listening ? (
        <Pressable onPress={onVoice} disabled={disabled} accessibilityLabel="음성 대화" style={styles.hit}>
          <Ionicons name="pulse-outline" size={22} color={disabled ? colors.disabled : colors.text} />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    marginHorizontal: 16,
    minHeight: 52,
    borderRadius: 26,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    paddingLeft: 20,
    paddingRight: 6,
    gap: 2,
  },
  barListening: {
    backgroundColor: colors.card,
    borderWidth: 1.5,
    borderColor: colors.text,
  },
  input: { flex: 1, minWidth: 0, fontSize: 15, color: colors.text, paddingVertical: 12 },
  inputDisabled: { color: colors.placeholder },
  hit: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  send: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.peach,
    alignItems: "center",
    justifyContent: "center",
  },
  sendOff: { opacity: 0.45 },
});
