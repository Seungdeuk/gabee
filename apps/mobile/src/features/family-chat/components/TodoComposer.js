import { Ionicons } from "@expo/vector-icons";
import { useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { canSubmitTitle, cleanTitle, DUE_CHIPS, dueFromChip, TITLE_MAX } from "../todoUtils";
import ChipRow from "./ChipRow";

const NO_ASSIGNEE = "none";

/**
 * 하단 할 일 추가줄: 제목 입력 + 보내기, 그 위에 담당자 칩과 기한 칩. 보내는 중에는 다시 눌러도 한 번만 보낸다.
 * @param {{ members: { id: string, name: string }[], onAdd: (body: { title: string, assignee_id: string | null, due_date: string | null, source: "manual" }) => Promise<string> }} props onAdd 는 오류 문구(성공이면 빈 문자열)를 돌려준다
 */
export default function TodoComposer({ members, onAdd }) {
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState(NO_ASSIGNEE);
  const [dueKey, setDueKey] = useState("none");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false); // 상태는 다시 그려진 뒤에야 바뀌어서, 같은 순간의 두 번째 누름은 ref 로 막는다
  const assigneeOptions = useMemo(() => [{ key: NO_ASSIGNEE, label: "담당자 없음" }, ...members.map((m) => ({ key: m.id, label: m.name }))], [members]);
  const dueOptions = DUE_CHIPS.map((c) => ({ key: c.key, label: c.label }));
  const ok = canSubmitTitle(title) && !sending;

  const submit = async () => {
    if (sendingRef.current || !canSubmitTitle(title)) return;
    sendingRef.current = true;
    setSending(true);
    setError("");
    const message = await onAdd({ title: cleanTitle(title), assignee_id: assignee === NO_ASSIGNEE ? null : assignee, due_date: dueFromChip(dueKey), source: "manual" });
    if (message) setError(message);
    else {
      setTitle("");
      setAssignee(NO_ASSIGNEE);
      setDueKey("none");
    }
    sendingRef.current = false;
    setSending(false);
  };

  return (
    <View style={styles.wrap}>
      <ChipRow label="담당자" options={assigneeOptions} value={assignee} onChange={setAssignee} />
      <ChipRow label="기한" options={dueOptions} value={dueKey} onChange={setDueKey} />
      {error ? (
        <Text style={styles.error} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={title}
          onChangeText={setTitle}
          maxLength={TITLE_MAX}
          placeholder="할 일을 적어 주세요"
          placeholderTextColor={colors.placeholder}
          returnKeyType="send"
          onSubmitEditing={submit}
          accessibilityLabel="할 일 제목"
        />
        <Pressable onPress={submit} disabled={!ok} accessibilityRole="button" accessibilityLabel="할 일 추가" aria-disabled={!ok} style={[styles.send, !ok && styles.sendOff]}>
          <Ionicons name="arrow-up" size={22} color={ok ? colors.text : colors.disabled} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.card, borderTopWidth: 1, borderTopColor: colors.divider, gap: spacing.xs },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  input: { flex: 1, minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.card, backgroundColor: colors.surface, ...font.body, color: colors.text },
  send: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  sendOff: { backgroundColor: colors.divider },
  error: { ...font.caption, color: colors.danger },
});
