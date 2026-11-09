import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 글자가 흐려 읽기 어려웠던 줄을 채팅에서 바로 확인하는 카드.
 * 줄마다 읽어 낸 글이 입력칸에 들어 있고, 맞으면 "모두 맞아요", 틀린 곳을 고쳤으면 "고쳐서 저장"을 누른다.
 * @param {{ lines: string[], done: boolean, onSubmit: (edits: string[]) => Promise<void> }} props
 */
export default function DoubtCard({ lines, done, onSubmit }) {
  const [edits, setEdits] = useState(lines);
  const [busy, setBusy] = useState(false);
  const changed = edits.some((e, i) => e.trim() !== lines[i]);

  if (done) {
    return (
      <View style={[styles.card, styles.done]}>
        <Ionicons name="checkmark-circle" size={18} color={colors.success} />
        <Text style={styles.doneText}>확인했어요. 기록에 반영했어요.</Text>
      </View>
    );
  }

  const submit = async () => {
    setBusy(true);
    try {
      await onSubmit(edits.map((e) => e.trim()));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.title}>읽어 낸 내용 중 이 줄이 확실하지 않아요</Text>
      <Text style={styles.sub}>
        {lines.some((l) => l.includes("[판독불가]"))
          ? "[판독불가]는 못 읽은 글자예요. 원본을 보고 맞는 글자로 고쳐 주세요."
          : "맞으면 그대로 두고, 틀린 곳은 고쳐 주세요."}
      </Text>
      {lines.map((line, i) => (
        <TextInput
          key={`${i}-${line}`}
          style={styles.input}
          value={edits[i]}
          onChangeText={(v) => setEdits((prev) => prev.map((p, j) => (j === i ? v : p)))}
          editable={!busy}
          multiline
          accessibilityLabel={`확인할 줄 ${i + 1}`}
        />
      ))}
      <View style={styles.row}>
        <Pressable onPress={submit} disabled={busy || changed} accessibilityRole="button" style={[styles.btn, styles.ghost, (busy || changed) && styles.off]}>
          <Text style={styles.ghostText}>모두 맞아요</Text>
        </Pressable>
        <Pressable onPress={submit} disabled={busy || !changed} accessibilityRole="button" style={[styles.btn, styles.main, (busy || !changed) && styles.off]}>
          {busy ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.mainText}>고쳐서 저장</Text>}
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
  row: { flexDirection: "row", gap: 8, marginTop: 4 },
  btn: { flex: 1, minHeight: 42, borderRadius: 21, alignItems: "center", justifyContent: "center" },
  ghost: { backgroundColor: colors.surface },
  ghostText: { fontSize: 14, fontWeight: "600", color: colors.text },
  main: { backgroundColor: colors.dark },
  mainText: { fontSize: 14, fontWeight: "600", color: colors.onDark },
  off: { opacity: 0.4 },
  done: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.successSoft, borderColor: colors.successSoft },
  doneText: { fontSize: 13, color: colors.success },
});
