import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

import { enableAi, getAiSettings } from "../api";
import { AI_OFF_ASK_MANAGER, AI_OFF_BODY, AI_OFF_TITLE } from "../errors";

/**
 * 가족 AI 가 꺼져 있을 때 보이는 안내 카드. 켤 수 있는 사람(소유자·관리자)에게만 "AI 사용 켜기" 버튼을 보여 준다.
 * 켜기는 버튼을 눌렀을 때만 하고, 질문은 자동으로 다시 보내지 않는다.
 * @param {{ onEnabled: () => void }} props 켜기에 성공하면 부른다(카드가 사라지고 다시 질문하라는 안내가 나온다)
 */
export default function AiOffCard({ onEnabled }) {
  const [canManage, setCanManage] = useState(null); // null: 확인 중
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    getAiSettings()
      .then((s) => alive && setCanManage(s.canManage))
      .catch(() => alive && setCanManage(false));
    return () => {
      alive = false;
    };
  }, []);

  const turnOn = async () => {
    setBusy(true);
    setError("");
    try {
      await enableAi();
      onEnabled();
    } catch (e) {
      setError(e?.message || "AI를 켜지 못했어요. 잠시 후 다시 시도해 주세요.");
      setBusy(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.title}>{AI_OFF_TITLE}</Text>
      <Text style={styles.body}>{AI_OFF_BODY}</Text>
      {canManage === null ? <ActivityIndicator color={colors.textMuted} /> : null}
      {canManage === true ? (
        <Pressable onPress={turnOn} disabled={busy} accessibilityRole="button" style={[styles.btn, busy && styles.off]}>
          {busy ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.btnText}>AI 사용 켜기</Text>}
        </Pressable>
      ) : null}
      {canManage === false ? <Text style={styles.note}>{AI_OFF_ASK_MANAGER}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 14, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, gap: 8 },
  title: { fontSize: 14, fontWeight: "700", color: colors.text },
  body: { fontSize: 13, lineHeight: 19, color: colors.textSub },
  btn: { minHeight: 42, borderRadius: 21, alignItems: "center", justifyContent: "center", backgroundColor: colors.dark, marginTop: 4 },
  btnText: { fontSize: 14, fontWeight: "600", color: colors.onDark },
  off: { opacity: 0.4 },
  note: { fontSize: 13, fontWeight: "600", color: colors.text },
  error: { fontSize: 12, color: colors.danger },
});
