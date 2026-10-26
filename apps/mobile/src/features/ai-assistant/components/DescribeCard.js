import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/theme";

const MAX_LENGTH = 200;

/**
 * 글자가 없는 사진에 사용자가 한 줄 설명을 다는 채팅 카드.
 * mode: "edit"(입력 중) | "done"(저장함) | "skipped"(나중에 하기로 함)
 * onSubmit 이 실패(throw)하면 카드 안에 오류를 보이고 다시 시도할 수 있다.
 * @param {{ mode: "edit" | "done" | "skipped", onSubmit: (text: string) => Promise<void>, onSkip: () => void }} props
 */
export default function DescribeCard({ mode, onSubmit, onSkip }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const empty = text.trim().length === 0;

  if (mode === "done") {
    return (
      <View style={[styles.card, styles.done]} accessibilityLiveRegion="polite">
        <Ionicons name="checkmark-circle" size={18} color={colors.success} />
        <Text style={styles.doneText}>저장했어요. 이제 이 설명으로 찾을 수 있어요</Text>
      </View>
    );
  }

  if (mode === "skipped") {
    return (
      <View style={[styles.card, styles.skipped]}>
        <Ionicons name="time-outline" size={18} color={colors.textMuted} />
        <Text style={styles.skippedText}>나중에 기록에서 설명을 달 수 있어요</Text>
      </View>
    );
  }

  const submit = async () => {
    if (empty || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit(text.trim());
    } catch (e) {
      setError(e?.message || "저장하지 못했어요.");
      setBusy(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.title}>이 사진은 어떤 사진인가요?</Text>
      <Text style={styles.sub}>글자가 없어서 직접 알려 주시면 나중에 말로 찾을 수 있어요</Text>
      <TextInput
        style={styles.input}
        value={text}
        onChangeText={setText}
        editable={!busy}
        maxLength={MAX_LENGTH}
        returnKeyType="done"
        onSubmitEditing={submit}
        accessibilityLabel="사진 설명 입력"
      />
      <Text style={styles.count} accessibilityLabel={`${MAX_LENGTH - text.length}자 더 쓸 수 있어요`}>
        {MAX_LENGTH - text.length}자 남음
      </Text>
      {error ? (
        <Text style={styles.error} accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : null}
      <View style={styles.row}>
        <Pressable onPress={onSkip} disabled={busy} accessibilityRole="button" style={[styles.btn, styles.ghost, busy && styles.off]}>
          <Text style={styles.ghostText}>나중에 할게요</Text>
        </Pressable>
        <Pressable
          onPress={submit}
          disabled={busy || empty}
          accessibilityRole="button"
          accessibilityLabel={error ? "설명 다시 저장" : "설명 저장"}
          style={[styles.btn, styles.main, (busy || empty) && styles.off]}
        >
          {busy ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.mainText}>{error ? "다시 시도" : "저장"}</Text>}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 14, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, gap: 8 },
  title: { fontSize: 14, fontWeight: "700", color: colors.text },
  sub: { fontSize: 12, color: colors.textMuted },
  input: { minHeight: 42, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 12, backgroundColor: colors.honeySoft, fontSize: 14, color: colors.text },
  count: { alignSelf: "flex-end", fontSize: 11, color: colors.textMuted },
  error: { fontSize: 12, color: colors.danger },
  row: { flexDirection: "row", gap: 8, marginTop: 4 },
  btn: { flex: 1, minHeight: 42, borderRadius: 21, alignItems: "center", justifyContent: "center" },
  ghost: { backgroundColor: colors.surface },
  ghostText: { fontSize: 14, fontWeight: "600", color: colors.text },
  main: { backgroundColor: colors.dark },
  mainText: { fontSize: 14, fontWeight: "600", color: colors.onDark },
  off: { opacity: 0.4 },
  done: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.successSoft, borderColor: colors.successSoft },
  doneText: { flex: 1, fontSize: 13, color: colors.success },
  skipped: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderColor: colors.surface },
  skippedText: { flex: 1, fontSize: 13, color: colors.textMuted },
});
