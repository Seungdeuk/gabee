import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import { useEffect, useRef, useState } from "react";
import { Alert, InteractionManager, Pressable, StyleSheet, TextInput, View } from "react-native";

import { colors } from "@/theme";

import AttachSheet from "./AttachSheet";

/**
 * 하단 둥근 입력창.
 * - idle: 옅은 꿀색 바탕, 마이크(말로 묻기)와 보내기 버튼(글자가 있을 때 켜진다)
 * - listening: 흰 바탕에 진한 테두리, 마이크 자리가 닫기(×)로 바뀌고 보내기는 그대로
 * - 왼쪽 + 버튼: 앨범/카메라에서 사진을, 또는 파일(PDF·문서 등)을 골라 onAttach 로 넘긴다
 * - disabled: 가비가 답하는 동안 입력을 막는다
 *
 * 음성 입력: 마이크를 누르면 폰의 음성 인식이 켜지고, 인식된 글자(voiceText)가 입력창에 채워진다.
 * 자동으로 보내지 않는다. 사용자가 글자를 확인·고친 뒤 보내기를 눌러야 전송된다.
 * TODO: 음성 대화(말로 주고받기) 버튼은 기능이 생기면 다시 둔다. 지금은 마이크와 같은 동작이라 뺐다.
 *
 * @param {{ mode: "idle" | "listening" | "disabled", voiceText?: string, onSend: (text: string, options: { voice: boolean }) => void, onMic: () => void, onAttach: (file: { uri: string, name?: string, type?: string, isImage: boolean }) => void }} props
 */
export default function ChatInput({ mode, voiceText = "", onSend, onMic, onAttach }) {
  const [text, setText] = useState("");
  const [sheet, setSheet] = useState(false);
  const listening = mode === "listening";
  const disabled = mode === "disabled";
  const canSend = text.trim().length > 0 && !disabled;
  const baseRef = useRef(""); // 말하기 시작 전에 이미 쳐 둔 글자(지우지 않고 뒤에 이어 붙인다)
  const usedVoice = useRef(false); // 이번 글에 음성으로 받은 부분이 있는지(전송 때 voice 표시)
  const textRef = useRef(text);
  textRef.current = text;

  useEffect(() => {
    if (listening) baseRef.current = textRef.current.trim();
  }, [listening]);

  useEffect(() => {
    if (!voiceText) return;
    const base = baseRef.current;
    setText(base ? `${base} ${voiceText}` : voiceText);
    usedVoice.current = true;
  }, [voiceText]);

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
      onAttach({ uri: asset.uri, name: asset.fileName ?? undefined, type: asset.mimeType ?? undefined, isImage: true });
    } catch (e) {
      Alert.alert("사진을 가져오지 못했어요", `잠시 후 다시 시도해 주세요.
(${e?.message ?? "알 수 없는 오류"})`);
    }
  };

  const pickFile = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({ type: "*/*", copyToCacheDirectory: true, multiple: false });
      if (result.canceled || !result.assets?.length) return;
      const asset = result.assets[0];
      const isImage = (asset.mimeType ?? "").startsWith("image/");
      onAttach({ uri: asset.uri, name: asset.name, type: asset.mimeType ?? "application/octet-stream", isImage });
    } catch (e) {
      Alert.alert("파일을 가져오지 못했어요", `잠시 후 다시 시도해 주세요.
(${e?.message ?? "알 수 없는 오류"})`);
    }
  };

  const attach = () => setSheet(true);

  /** 시트를 닫은 뒤에 고른 창을 연다(두 창이 겹쳐 뜨면 일부 폰에서 열리지 않는다). */
  const choose = (key) => {
    setSheet(false);
    // 시트 창이 완전히 사라진 뒤에 연다. 안드로이드는 창이 겹쳐 있으면 갤러리가 열리지 않는 경우가 있다
    InteractionManager.runAfterInteractions(() => {
      setTimeout(() => (key === "file" ? pickFile() : pick(key === "camera")), 500);
    });
  };

  const submit = () => {
    if (!canSend) return;
    onSend(text, { voice: usedVoice.current });
    usedVoice.current = false;
    baseRef.current = "";
    setText("");
  };

  return (
    <View style={[styles.bar, listening && styles.barListening]}>
      <Pressable onPress={attach} disabled={disabled} accessibilityLabel="사진이나 파일 올리기" style={styles.hit}>
        <Ionicons name="add" size={26} color={disabled ? colors.disabled : colors.text} />
      </Pressable>
      <TextInput
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
      <AttachSheet visible={sheet} onClose={() => setSheet(false)} onPick={choose} />
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
