import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import { useEffect, useRef, useState } from "react";
import { Alert, Pressable, StyleSheet, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 하단 둥근 입력창.
 * - idle: 옅은 꿀색 바탕, 마이크(말로 묻기)와 보내기 버튼(글자가 있을 때 켜진다)
 * - listening: 흰 바탕에 진한 테두리, 마이크 자리가 닫기(×)로 바뀌고 보내기는 그대로
 * - 왼쪽 + 버튼: 앨범/카메라에서 사진을 골라 onAttach 로 넘긴다
 * - disabled: 가비가 답하는 동안 입력을 막는다
 *
 * TODO: 음성 인식은 폰 키보드의 받아쓰기를 쓴다. 앱 안에서 직접 인식하려면 음성 인식 모듈을 붙인다.
 * TODO: 음성 대화(말로 주고받기) 버튼은 기능이 생기면 다시 둔다. 지금은 마이크와 같은 동작이라 뺐다.
 *
 * @param {{ mode: "idle" | "listening" | "disabled", onSend: (text: string, options: { voice: boolean }) => void, onMic: () => void, onAttach: (file: { uri: string, name?: string, type?: string }) => void }} props
 */
export default function ChatInput({ mode, onSend, onMic, onAttach }) {
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

  const pick = async (fromCamera) => {
    try {
      const ask = fromCamera ? ImagePicker.requestCameraPermissionsAsync : ImagePicker.requestMediaLibraryPermissionsAsync;
      const { granted } = await ask();
      if (!granted) {
        Alert.alert("권한이 필요해요", `${fromCamera ? "카메라" : "앨범"} 접근을 허용해야 사진을 올릴 수 있어요. 폰 설정에서 허용해 주세요.`);
        return;
      }
      const launch = fromCamera ? ImagePicker.launchCameraAsync : ImagePicker.launchImageLibraryAsync;
      const result = await launch({ mediaTypes: ["images"], quality: 0.8 });
      if (result.canceled || !result.assets?.length) return;
      const asset = result.assets[0];
      onAttach({ uri: asset.uri, name: asset.fileName ?? undefined, type: asset.mimeType ?? undefined });
    } catch {
      Alert.alert("사진을 가져오지 못했어요", "잠시 후 다시 시도해 주세요.");
    }
  };

  const attach = () => {
    Alert.alert("사진 올리기", "어디에서 가져올까요?", [
      { text: "앨범에서 고르기", onPress: () => pick(false) },
      { text: "카메라로 찍기", onPress: () => pick(true) },
      { text: "취소", style: "cancel" },
    ]);
  };

  const submit = () => {
    if (!canSend) return;
    onSend(text, { voice: listening });
    setText("");
  };

  return (
    <View style={[styles.bar, listening && styles.barListening]}>
      <Pressable onPress={attach} disabled={disabled} accessibilityLabel="사진 올리기" style={styles.hit}>
        <Ionicons name="add" size={26} color={disabled ? colors.disabled : colors.text} />
      </Pressable>
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

      {/* 오른쪽 끝은 항상 보내기. 마이크(음성 입력 중에는 닫기)는 그 왼쪽에 둔다. */}
      <Pressable onPress={onMic} disabled={disabled} accessibilityLabel={listening ? "음성 입력 끝내기" : "말로 묻기"} style={styles.hit}>
        <Ionicons name={listening ? "close" : "mic-outline"} size={22} color={disabled ? colors.disabled : listening ? colors.textMuted : colors.text} />
      </Pressable>

      <Pressable onPress={submit} disabled={!canSend} accessibilityLabel="보내기" style={styles.hit}>
        <View style={[styles.send, !canSend && styles.sendOff]}>
          <Ionicons name="arrow-up" size={20} color={colors.text} />
        </View>
      </Pressable>
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
    paddingLeft: 6,
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
