import { useMemo, useRef, useState } from "react";
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { buildEditPatch, canSubmitTitle, chipForDue, DUE_CHIPS, dueLabel, TITLE_MAX } from "../todoUtils";
import ChipRow from "./ChipRow";

const NO_ASSIGNEE = "none";

/**
 * 할 일 고치기 창: 제목, 담당자·기한 칩, 지우기(확인 단계 뒤). 바뀐 항목만 저장한다. 부모가 todo 마다 key 를 달아 새로 열게 한다.
 * @param {{ todo: { id: string, title: string, assignee_id: string | null, due_date: string | null }, members: { id: string, name: string }[], onClose: () => void, onSave: (patch: object) => Promise<string>, onDelete: () => Promise<string> }} props onSave·onDelete 는 오류 문구(성공이면 빈 문자열)를 돌려준다
 */
export default function TodoEditModal({ todo, members, onClose, onSave, onDelete }) {
  const [today] = useState(() => new Date()); // 창을 연 때의 날짜로 고정: 자정을 넘겨도 '오늘' 칩이 바뀌지 않는다
  const [title, setTitle] = useState(todo.title);
  const [assignee, setAssignee] = useState(todo.assignee_id ?? NO_ASSIGNEE);
  const [dueKey, setDueKey] = useState(chipForDue(todo.due_date, today) ?? "keep");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const busyRef = useRef(false);
  const assigneeOptions = useMemo(() => [{ key: NO_ASSIGNEE, label: "담당자 없음" }, ...members.map((m) => ({ key: m.id, label: m.name }))], [members]);
  const dueOptions = useMemo(() => {
    const base = DUE_CHIPS.map((c) => ({ key: c.key, label: c.label }));
    return dueKey === "keep" ? [{ key: "keep", label: `현재 ${dueLabel(todo.due_date)?.text ?? "기한"}` }, ...base] : base;
  }, [dueKey, todo.due_date]);

  const run = async (call) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    const message = await call();
    busyRef.current = false;
    setBusy(false);
    if (message) setError(message);
    else onClose();
  };

  const save = () => {
    const patch = buildEditPatch(todo, { title, assigneeId: assignee === NO_ASSIGNEE ? null : assignee, dueKey }, today);
    if (Object.keys(patch).length === 0) return onClose();
    return run(() => onSave(patch));
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="고치기 닫기" />
        <View style={styles.sheet}>
          <Text style={styles.heading} accessibilityRole="header">
            할 일 고치기
          </Text>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
            <TextInput
              style={styles.input}
              value={title}
              onChangeText={setTitle}
              maxLength={TITLE_MAX}
              placeholder="할 일 제목"
              placeholderTextColor={colors.placeholder}
              accessibilityLabel="할 일 제목"
            />
            <Text style={styles.label}>담당자</Text>
            <ChipRow label="담당자" options={assigneeOptions} value={assignee} onChange={setAssignee} />
            <Text style={styles.label}>기한</Text>
            <ChipRow label="기한" options={dueOptions} value={dueKey} onChange={setDueKey} />
            {error ? (
              <Text style={styles.error} accessibilityRole="alert">
                {error}
              </Text>
            ) : null}
            {confirming ? (
              <View style={styles.confirm}>
                <Text style={styles.body}>이 할 일을 지울까요? 되돌릴 수 없어요.</Text>
                <View style={styles.row}>
                  <Button label="지우기" small onPress={() => run(onDelete)} disabled={busy} />
                  <Button label="취소" small variant="secondary" onPress={() => setConfirming(false)} disabled={busy} />
                </View>
              </View>
            ) : (
              <View style={styles.row}>
                <Button label="저장" onPress={save} disabled={busy || !canSubmitTitle(title)} />
                <Button label="지우기" variant="secondary" onPress={() => setConfirming(true)} disabled={busy} />
              </View>
            )}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.text, opacity: 0.4 },
  sheet: { maxHeight: "85%", backgroundColor: colors.background, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card, paddingTop: spacing.lg },
  heading: { ...font.cardTitle, color: colors.text, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  content: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  input: { minHeight: 46, paddingHorizontal: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, ...font.body, color: colors.text },
  label: { ...font.caption, color: colors.textMuted },
  row: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  confirm: { gap: spacing.sm, marginTop: spacing.sm },
  body: { ...font.body, color: colors.text },
  error: { ...font.caption, color: colors.danger },
});
