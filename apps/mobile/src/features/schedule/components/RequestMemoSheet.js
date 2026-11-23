import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { REQUEST_MEMO_MAX, memoChars, memoGuide } from "../memo_edit";
import BottomSheet from "./BottomSheet";
import { TextBox } from "./FormControls";

/**
 * 보낸 부탁의 "메모 바꾸기" 시트. 지금 메모가 처음부터 채워져 있고, 글자 수(n / 2000)와 안내를 보인다.
 * 바뀐 게 없거나 2000자를 넘으면 저장할 수 없다. 메모를 비우고 저장하면 메모가 지워진다. 열 때마다 새로 만들어 쓴다.
 * 수락한 분의 일정에는 반영되지 않는다는 점을 항상 보인다.
 * @param {{ current: string, saving?: boolean, onClose: () => void, onSave: (memo: string) => void }} props
 */
export default function RequestMemoSheet({ current, saving = false, onClose, onSave }) {
  const [draft, setDraft] = useState(current);
  const { message, canSave } = memoGuide(current, draft);
  const disabled = !canSave || saving;

  return (
    <BottomSheet visible onClose={onClose}>
      <Text style={styles.title}>메모 바꾸기</Text>
      <TextBox value={draft} onChangeText={setDraft} placeholder="메모를 적어 주세요" multiline />
      <Text style={styles.count}>{`${memoChars(draft)} / ${REQUEST_MEMO_MAX}`}</Text>
      <Text style={styles.hint}>이미 수락한 분의 일정에는 반영되지 않아요</Text>
      {message ? (
        <View style={styles.notice} accessibilityRole="alert">
          <Text style={styles.noticeText}>{message}</Text>
        </View>
      ) : null}
      <View style={styles.row}>
        <Pressable onPress={onClose} style={[styles.button, styles.close]} accessibilityRole="button">
          <Text style={styles.closeText}>닫기</Text>
        </Pressable>
        <Pressable
          onPress={() => onSave(draft.trim())}
          disabled={disabled}
          style={[styles.button, styles.save, disabled && styles.disabled]}
          accessibilityRole="button"
          accessibilityState={{ disabled }}
        >
          <Text style={styles.saveText}>저장</Text>
        </Pressable>
      </View>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  count: { ...font.caption, color: colors.textMuted, textAlign: "right" },
  hint: { ...font.caption, color: colors.textMuted },
  notice: { padding: 10, borderRadius: radius.button, backgroundColor: colors.surfaceStrong },
  noticeText: { fontSize: 14, color: colors.text },
  row: { flexDirection: "row", gap: spacing.sm, marginTop: 6 },
  button: { flex: 1, minHeight: 48, alignItems: "center", justifyContent: "center", borderRadius: radius.button },
  close: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  closeText: { fontSize: 15, fontWeight: "500", color: colors.text },
  save: { backgroundColor: colors.peach },
  saveText: { fontSize: 15, fontWeight: "700", color: colors.text },
  disabled: { opacity: 0.45 },
});
