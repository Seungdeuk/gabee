import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import BottomSheet from "../../components/BottomSheet";
import { FormField, TextBox } from "../../components/FormControls";
import { CHEER_KINDS, CHEER_MESSAGES, cheerTone } from "../logic";

const KIND_ICON = { love: "heart-outline", best: "thumbs-up-outline", well: "star-outline" };

/**
 * 응원 보내기 시트. 종류 하나, 한마디(문구 두 개 또는 직접 쓰기), "가족 대화방에도 남기기" 표시를 고르고 보낸다.
 * 보내면 onSend({ kind, text, groupChat }) 를 부른다. 실제 전송은 하지 않는다(부모가 이 폰에 기록).
 * @param {{ visible: boolean, onClose: () => void, title: string, subtitle: string, onSend: (cheer: { kind: string, text: string, groupChat: boolean }) => void }} props
 */
export default function CheerSheet({ visible, onClose, title, subtitle, onSend }) {
  const [kind, setKind] = useState("love");
  const [picked, setPicked] = useState("");
  const [custom, setCustom] = useState("");
  const [groupChat, setGroupChat] = useState(true);
  const [error, setError] = useState("");

  // 시트를 열 때마다 처음 상태로 돌린다.
  useEffect(() => {
    if (!visible) return;
    setKind("love");
    setPicked("");
    setCustom("");
    setGroupChat(true);
    setError("");
  }, [visible]);

  const send = () => {
    const text = custom.trim() || picked;
    if (!text) {
      setError("한마디를 고르거나 직접 적어 주세요");
      return;
    }
    onSend({ kind, text, groupChat });
  };

  return (
    <BottomSheet visible={visible} onClose={onClose}>
      <Text style={styles.title} accessibilityRole="header">
        {title}
      </Text>
      <Text style={styles.subtitle}>{subtitle}</Text>

      <View style={styles.kindRow}>
        {CHEER_KINDS.map((k) => {
          const on = kind === k.key;
          return (
            <Pressable
              key={k.key}
              onPress={() => setKind(k.key)}
              style={[styles.kind, on ? [styles.kindOn, { backgroundColor: cheerTone(k.key).bg, borderColor: cheerTone(k.key).border }] : styles.kindOff]}
              accessibilityRole="button"
              accessibilityLabel={k.label}
              accessibilityState={{ selected: on }}
            >
              <Ionicons name={KIND_ICON[k.key]} size={24} color={colors.text} />
              <Text style={[styles.kindText, on && styles.kindTextOn]}>{k.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.label}>한마디 고르기</Text>
      {CHEER_MESSAGES.map((message) => {
        const on = !custom.trim() && picked === message;
        return (
          <Pressable
            key={message}
            onPress={() => {
              setPicked(message);
              setCustom("");
              setError("");
            }}
            style={[styles.message, on && styles.messageOn]}
            accessibilityRole="button"
            accessibilityLabel={message}
            accessibilityState={{ selected: on }}
          >
            <Text style={styles.messageText}>{message}</Text>
          </Pressable>
        );
      })}

      <FormField label="직접 쓰기">
        <TextBox
          value={custom}
          onChangeText={(text) => {
            setCustom(text);
            setError("");
          }}
          placeholder="한마디를 적어 보세요"
        />
      </FormField>

      <Pressable
        onPress={() => setGroupChat((v) => !v)}
        style={styles.check}
        accessibilityRole="checkbox"
        accessibilityLabel="가족 대화방에도 남기기"
        accessibilityState={{ checked: groupChat }}
      >
        <View style={[styles.box, groupChat && styles.boxOn]}>
          {groupChat ? <Ionicons name="checkmark" size={16} color={colors.onDark} /> : null}
        </View>
        <View style={styles.checkText}>
          <Text style={styles.checkLabel}>가족 대화방(도란도란)에도 남기기</Text>
          <Text style={styles.checkSub}>표시만 해 둬요. 아직 채팅으로 보내지지는 않아요</Text>
        </View>
      </Pressable>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable onPress={send} style={styles.send} accessibilityRole="button" accessibilityLabel="응원 보내기">
        <Text style={styles.sendText}>응원 보내기</Text>
      </Pressable>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  subtitle: { ...font.caption, color: colors.textSub, marginBottom: spacing.sm },
  kindRow: { flexDirection: "row", gap: 8 },
  kind: { flex: 1, minHeight: 72, borderRadius: radius.button, alignItems: "center", justifyContent: "center", gap: 4 },
  kindOn: { borderWidth: 1, borderColor: colors.primary },
  kindOff: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  kindText: { fontSize: 14, color: colors.text },
  kindTextOn: { fontWeight: "700" },
  label: { fontSize: 14, fontWeight: "500", color: colors.text, marginTop: spacing.sm },
  message: {
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    justifyContent: "center",
  },
  // 선택된 한마디는 외곽선 없이 노란 채움만(테두리 색을 바탕색과 같게 둬 크기를 맞춘다)
  messageOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  messageText: { fontSize: 15, color: colors.text },
  check: { minHeight: 56, flexDirection: "row", alignItems: "center", gap: 12, marginTop: spacing.sm },
  box: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
  },
  boxOn: { backgroundColor: colors.success, borderColor: colors.success },
  checkText: { flex: 1, gap: 2 },
  checkLabel: { fontSize: 15, color: colors.text },
  checkSub: { ...font.caption, color: colors.textSub },
  error: { fontSize: 14, color: colors.danger, textAlign: "center" },
  send: { minHeight: 56, borderRadius: radius.button, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center", marginTop: spacing.sm },
  sendText:{ fontSize: 16, fontWeight: "700", color: colors.text },
});
