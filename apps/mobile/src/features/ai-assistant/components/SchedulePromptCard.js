import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

/**
 * 문서·사진을 올려 분석이 끝난 직후 "이런 내용이네요, 일정에 넣을까요?" 를 묻는 채팅 카드.
 * mode: "ask"(묻는 중) | "done"(일정에 넣기를 눌렀다) | "skipped"(아니요)
 * "일정에 넣기"는 채팅으로 요청을 보낸다(그 뒤는 일반 일정 요청과 같다: 바로 등록하거나 확인 카드를 보여 준다).
 * @param {{ mode: "ask" | "done" | "skipped", title: string, date: string, kindLabel?: string, onAccept: () => void, onSkip: () => void }} props
 */
export default function SchedulePromptCard({ mode, title, date, kindLabel, onAccept, onSkip }) {
  if (mode === "done") {
    return (
      <View style={[styles.card, styles.done]} accessibilityLiveRegion="polite">
        <Ionicons name="checkmark-circle" size={18} color={colors.success} />
        <Text style={styles.doneText}>일정에 넣어 달라고 요청했어요</Text>
      </View>
    );
  }
  if (mode === "skipped") {
    return (
      <View style={[styles.card, styles.skipped]}>
        <Ionicons name="time-outline" size={18} color={colors.textMuted} />
        <Text style={styles.skippedText}>일정에 넣지 않았어요. 필요하면 말로 요청해 주세요</Text>
      </View>
    );
  }
  return (
    <View style={styles.card} accessibilityLabel="일정 제안 카드">
      <View style={styles.head}>
        <Ionicons name="calendar-outline" size={16} color={colors.accent} />
        <Text style={styles.title}>이런 내용이네요, 일정에 넣을까요?</Text>
      </View>
      <Text style={styles.line}>{title}</Text>
      <Text style={styles.sub}>{[kindLabel, date].filter(Boolean).join(" · ")}</Text>
      <View style={styles.row}>
        <Pressable onPress={onSkip} accessibilityRole="button" accessibilityLabel="일정에 넣지 않기" style={[styles.btn, styles.ghost]}>
          <Text style={styles.ghostText}>아니요</Text>
        </Pressable>
        <Pressable onPress={onAccept} accessibilityRole="button" accessibilityLabel="일정에 넣기" style={[styles.btn, styles.main]}>
          <Text style={styles.mainText}>일정에 넣기</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 14, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, gap: 6 },
  head: { flexDirection: "row", alignItems: "center", gap: 6 },
  title: { fontSize: 14, fontWeight: "700", color: colors.text, flexShrink: 1 },
  line: { fontSize: 14, color: colors.text },
  sub: { fontSize: 12, color: colors.textMuted },
  row: { flexDirection: "row", gap: 8, marginTop: 4 },
  btn: { flex: 1, minHeight: 42, borderRadius: 21, alignItems: "center", justifyContent: "center" },
  ghost: { backgroundColor: colors.surface },
  ghostText: { fontSize: 14, fontWeight: "600", color: colors.text },
  main: { backgroundColor: colors.dark },
  mainText: { fontSize: 14, fontWeight: "600", color: colors.onDark },
  done: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.successSoft, borderColor: colors.successSoft },
  doneText: { flex: 1, fontSize: 13, color: colors.success },
  skipped: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderColor: colors.surface },
  skippedText: { flex: 1, fontSize: 13, color: colors.textMuted },
});
