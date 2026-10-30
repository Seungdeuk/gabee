import { useRef, useState } from "react";
import { KeyboardAvoidingView, Modal, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { MEMO_MAX, NICKNAME_MAX, validateNickname } from "../contactUtils";

/**
 * 별명·메모 편집 창. 나에게만 보이고 다른 가족에게는 보이지 않는다. 둘 다 비우고 저장하면 지워진다.
 * @param {{ row: { id: string, realName: string, nickname: string, memo: string }, onClose: () => void, onSave: (value: { nickname: string, memo: string }) => Promise<string> }} props onSave 는 오류 문구(성공이면 빈 문자열)를 돌려준다
 */
export default function NicknameModal({ row, onClose, onSave }) {
  const insets = useSafeAreaInsets(); // 안드로이드 내비게이션 바에 저장 버튼이 가려지지 않게
  const [nickname, setNickname] = useState(row.nickname);
  const [memo, setMemo] = useState(row.memo);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const busyRef = useRef(false);

  const save = async (value) => {
    if (busyRef.current) return;
    const problem = validateNickname(value.nickname, value.memo);
    if (problem) return setError(problem);
    busyRef.current = true;
    setBusy(true);
    setError("");
    const message = await onSave(value);
    busyRef.current = false;
    setBusy(false);
    if (message) setError(message);
    else onClose();
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.root} behavior="padding">
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="별명·메모 닫기" />
        <View style={[styles.sheet, { paddingBottom: spacing.xxl + insets.bottom }]}>
          <Text style={styles.heading} accessibilityRole="header">
            {row.realName}님 별명·메모
          </Text>
          <Text style={styles.hint}>나에게만 보여요. 다른 가족에게는 보이지 않아요.</Text>
          <TextInput
            style={styles.input}
            value={nickname}
            onChangeText={setNickname}
            maxLength={NICKNAME_MAX}
            placeholder="별명"
            placeholderTextColor={colors.placeholder}
            accessibilityLabel="별명"
          />
          <TextInput
            style={[styles.input, styles.memo]}
            value={memo}
            onChangeText={setMemo}
            maxLength={MEMO_MAX}
            multiline
            placeholder="메모"
            placeholderTextColor={colors.placeholder}
            accessibilityLabel="메모"
          />
          {error ? (
            <Text style={styles.error} accessibilityRole="alert">
              {error}
            </Text>
          ) : null}
          {confirming ? (
            <View style={styles.confirm}>
              <Text style={styles.hint}>별명과 메모를 모두 지울까요?</Text>
              <View style={styles.row}>
                <Button label="지우기" onPress={() => save({ nickname: "", memo: "" })} disabled={busy} />
                <Button label="취소" variant="secondary" onPress={() => setConfirming(false)} disabled={busy} />
              </View>
            </View>
          ) : (
            <View style={styles.row}>
              <Button label="저장" onPress={() => save({ nickname, memo })} disabled={busy} />
              <Button label="지우기" variant="secondary" onPress={() => setConfirming(true)} disabled={busy} />
            </View>
          )}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.text, opacity: 0.4 },
  sheet: { gap: spacing.sm, padding: spacing.lg, paddingBottom: spacing.xxl, backgroundColor: colors.background, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card },
  heading: { ...font.cardTitle, color: colors.text },
  hint: { ...font.caption, color: colors.textMuted },
  input: { minHeight: 46, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, ...font.body, color: colors.text },
  memo: { minHeight: 96, textAlignVertical: "top" },
  row: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  confirm: { gap: spacing.xs },
  error: { ...font.caption, color: colors.danger },
});
