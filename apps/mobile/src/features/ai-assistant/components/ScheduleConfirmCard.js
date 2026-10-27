import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { confirmScheduleAction } from "../api";
import { CANCELLED_TEXT, CARD_CANCELLED, CARD_DONE, CARD_PENDING, cardButtons } from "../scheduleCard";

/**
 * 채팅의 일정 확인 카드: 가족에게 공유해서 등록 / 일정 수정 / 일정 삭제. 서버는 채팅에서 바로 실행하지 않고, 사용자가 이 버튼을 눌러야 반영된다.
 * 처리했거나 취소하면 카드가 결과 한 줄로 바뀌고(onResolve 로 대화에 저장돼 다시 열어도 두 번 실행되지 않는다) 버튼은 사라진다.
 * 서버 오류(예: 등록에 필요한 제목이나 날짜가 없어요)는 카드 아래에 보여 주고 다시 누를 수 있게 둔다.
 * @param {{ card: object, onResolve?: (status: "done" | "cancelled", text: string) => void }} props
 */
export default function ScheduleConfirmCard({ card, onResolve }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const status = card.status ?? CARD_PENDING;

  if (status === CARD_DONE || status === CARD_CANCELLED) {
    const done = status === CARD_DONE;
    return (
      <View style={[styles.card, styles.resolved]} accessibilityLiveRegion="polite">
        <Ionicons name={done ? "checkmark-circle" : "close-circle-outline"} size={18} color={done ? colors.success : colors.textMuted} />
        <Text style={styles.resolvedText}>{done ? card.resultText || "반영했어요." : CANCELLED_TEXT}</Text>
      </View>
    );
  }

  const press = async (button) => {
    if (busy) return;
    if (button.key === "cancel") {
      onResolve?.(CARD_CANCELLED, "");
      return;
    }
    setBusy(button.key);
    setError("");
    try {
      const { text } = await confirmScheduleAction(card, button.share);
      onResolve?.(CARD_DONE, text);
    } catch (e) {
      setError(e?.message || "처리하지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy("");
    }
  };

  return (
    <View style={styles.card} accessibilityLabel="일정 확인 카드">
      <View style={styles.head}>
        <Ionicons name="calendar-outline" size={16} color={colors.accent} />
        <Text style={styles.title}>{card.title}</Text>
      </View>
      {card.lines.map((line, i) => (
        <Text key={`${i}-${line}`} style={styles.line}>
          {line}
        </Text>
      ))}
      {card.sharedWith.length > 0 ? <Text style={styles.share}>공유 대상 · {card.sharedWith.join(", ")}</Text> : null}
      {error ? (
        <Text style={styles.error} accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : null}
      <View style={styles.row}>
        {cardButtons(card).map((b) => (
          <Pressable
            key={b.key}
            onPress={() => press(b)}
            disabled={Boolean(busy)}
            accessibilityRole="button"
            accessibilityLabel={b.label}
            style={[styles.btn, b.tone === "ghost" ? styles.ghost : b.tone === "danger" ? styles.danger : styles.main, busy && styles.off]}
          >
            {busy === b.key ? <ActivityIndicator color={b.tone === "ghost" ? colors.text : colors.onDark} /> : <Text style={b.tone === "ghost" ? styles.ghostText : styles.mainText}>{b.label}</Text>}
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { marginTop: spacing.sm, padding: spacing.md, gap: spacing.xs, borderRadius: radius.md, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  title: { ...font.body, fontFamily: font.bodyStrong.fontFamily, color: colors.text, flexShrink: 1 },
  line: { ...font.body, color: colors.text },
  share: { ...font.caption, color: colors.textSub },
  error: { ...font.caption, color: colors.danger },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  btn: { minHeight: 40, minWidth: 72, paddingHorizontal: spacing.md, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  main: { backgroundColor: colors.accent },
  danger: { backgroundColor: colors.danger },
  ghost: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  off: { opacity: 0.6 },
  mainText: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.onDark },
  ghostText: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  resolved: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface },
  resolvedText: { ...font.caption, color: colors.textSub, flexShrink: 1 },
});
