import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, Share, StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 가비가 만든 메시지 초안. 승인하기 전에는 아무에게도 보내지지 않는다.
 * "확인하고 보내기"는 공유 시트를 열어 사용자가 직접 보내게 한다(가비는 메시지를 직접 보내지 않는다).
 * "고치기"를 누르면 문구를 바로 고칠 수 있다.
 *
 * @param {{ to: string, text: string, onChangeText: (text: string) => void }} props
 */
export default function DraftCard({ to, text, onChangeText }) {
  const [editing, setEditing] = useState(false);

  // TODO: 서버에 승인 기록을 남기고(승인 전 → 승인됨), 소통 탭의 대화로 이어 준다.
  const confirm = () => Share.share({ message: text });

  return (
    <View style={styles.wrap}>
      <View style={styles.card}>
        <Text style={styles.tag}>{to}에게 · 승인 전</Text>
        {editing ? (
          <TextInput
            style={styles.input}
            value={text}
            onChangeText={onChangeText}
            multiline
            autoFocus
            accessibilityLabel="메시지 초안 고치기"
          />
        ) : (
          <Text style={styles.text}>{text}</Text>
        )}
        <View style={styles.buttons}>
          <Pressable onPress={() => setEditing((v) => !v)} style={[styles.button, styles.edit]} accessibilityRole="button">
            <Text style={styles.editText}>{editing ? "고치기 끝" : "고치기"}</Text>
          </Pressable>
          <Pressable onPress={confirm} style={[styles.button, styles.send]} accessibilityRole="button">
            <Text style={styles.sendText}>확인하고 보내기</Text>
          </Pressable>
        </View>
      </View>
      <View style={styles.note}>
        <Ionicons name="information-circle-outline" size={14} color={colors.textMuted} />
        <Text style={styles.noteText}>가비는 메시지를 직접 보내지 않아요</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 10 },
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    padding: 16,
    gap: 12,
    backgroundColor: colors.card,
  },
  tag: {
    alignSelf: "flex-start",
    paddingVertical: 3,
    paddingHorizontal: 9,
    borderRadius: 6,
    overflow: "hidden",
    backgroundColor: colors.surfaceStrong,
    fontSize: 12,
    fontWeight: "700",
    color: colors.text,
  },
  text: { fontSize: 16, lineHeight: 25, color: colors.text },
  input: {
    fontSize: 16,
    lineHeight: 25,
    color: colors.text,
    padding: 10,
    borderRadius: 10,
    backgroundColor: colors.surface,
  },
  buttons: { flexDirection: "row", gap: 8 },
  button: { minHeight: 48, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  edit: { flex: 1, backgroundColor: colors.surface },
  editText: { fontSize: 15, fontWeight: "500", color: colors.text },
  send: { flex: 2, backgroundColor: colors.dark },
  sendText: { fontSize: 15, fontWeight: "700", color: colors.onDark },
  note: { flexDirection: "row", alignItems: "center", gap: 4 },
  noteText: { fontSize: 12, color: colors.textMuted },
});
