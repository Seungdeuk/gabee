import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import { deleteAllMemories, deleteMemory, listMemories, updateMemory } from "../api";

const MAX_TEXT = 200;

/**
 * 마이 > 가비의 기억: 내가 기억해 달라고 한 내용을 보고 고치고 지운다. 가족에게는 보이지 않는다.
 * @returns {import("react").ReactElement}
 */
export default function MemoriesScreen() {
  const router = useRouter();
  const [rows, setRows] = useState(null); // null: 불러오는 중
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null); // 고치는 중이면 { id, text }
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      setRows(await listMemories());
    } catch (e) {
      setRows([]);
      setError(e?.message || "기억을 불러오지 못했어요.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const back = () => {
    if (router.canGoBack()) router.back();
    else router.replace("/my");
  };

  const save = async () => {
    if (!editing || saving || !editing.text.trim()) return;
    setSaving(true);
    try {
      const saved = await updateMemory(editing.id, editing.text);
      setRows((prev) => (prev ?? []).map((r) => (r.id === saved.id ? saved : r)));
      setEditing(null);
    } catch (e) {
      Alert.alert("고치지 못했어요", e?.message || "잠시 후 다시 시도해 주세요.");
    } finally {
      setSaving(false);
    }
  };

  const removeOne = async (id) => {
    try {
      await deleteMemory(id);
      setRows((prev) => (prev ?? []).filter((r) => r.id !== id));
    } catch (e) {
      Alert.alert("지우지 못했어요", e?.message || "잠시 후 다시 시도해 주세요.");
    }
  };

  const removeAll = () => {
    Alert.alert("기억을 모두 지울까요?", "지운 내용은 되돌릴 수 없어요.", [
      { text: "취소", style: "cancel" },
      {
        text: "모두 지우기",
        style: "destructive",
        onPress: async () => {
          try {
            await deleteAllMemories();
            setRows([]);
          } catch (e) {
            Alert.alert("지우지 못했어요", e?.message || "잠시 후 다시 시도해 주세요.");
          }
        },
      },
    ]);
  };

  return (
    <Screen title="가비의 기억" left={<IconButton name="chevron-back" label="뒤로" onPress={back} />}>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.help}>가비에게 기억해 달라고 한 내용이에요. 나에게만 쓰이고 가족에게는 보이지 않아요.</Text>
        {rows === null ? <ActivityIndicator color={colors.accent} /> : null}
        {error ? (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error}</Text>
            <Button title="다시 시도" onPress={load} />
          </View>
        ) : null}
        {rows !== null && rows.length === 0 && !error ? (
          <View style={styles.empty}>
            <Ionicons name="bookmark-outline" size={28} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>아직 기억한 내용이 없어요</Text>
            <Text style={styles.help}>AI 채팅에서 “내가 좋아하는 팀은 T1이야. 기억해 줘”처럼 말해 보세요.</Text>
          </View>
        ) : null}
        {(rows ?? []).map((m) =>
          editing?.id === m.id ? (
            <View key={m.id} style={styles.editBox}>
              <TextInput
                style={styles.input}
                value={editing.text}
                onChangeText={(text) => setEditing({ id: m.id, text })}
                maxLength={MAX_TEXT}
                multiline
                autoFocus
                accessibilityLabel="기억 고치기"
              />
              <View style={styles.editActions}>
                <Pressable onPress={() => setEditing(null)} style={styles.editButton} accessibilityRole="button">
                  <Text style={styles.cancelText}>취소</Text>
                </Pressable>
                <Pressable
                  onPress={save}
                  disabled={saving || !editing.text.trim()}
                  style={[styles.editButton, styles.saveButton, (saving || !editing.text.trim()) && styles.disabled]}
                  accessibilityRole="button"
                >
                  <Text style={styles.saveText}>{saving ? "저장 중" : "저장"}</Text>
                </Pressable>
              </View>
            </View>
          ) : (
          <View key={m.id} style={styles.row}>
            <Text style={styles.rowText}>{m.text}</Text>
            <Pressable
              onPress={() => setEditing({ id: m.id, text: m.text })}
              hitSlop={8}
              style={styles.remove}
              accessibilityRole="button"
              accessibilityLabel={`${m.text} 고치기`}
            >
              <Ionicons name="create-outline" size={20} color={colors.textSub} />
            </Pressable>
            <Pressable
              onPress={() => removeOne(m.id)}
              hitSlop={8}
              style={styles.remove}
              accessibilityRole="button"
              accessibilityLabel={`${m.text} 지우기`}
            >
              <Ionicons name="trash-outline" size={20} color={colors.textSub} />
            </Pressable>
          </View>
          ),
        )}
        {(rows ?? []).length > 0 ? (
          <Pressable onPress={removeAll} style={styles.removeAll} accessibilityRole="button">
            <Text style={styles.removeAllText}>모두 지우기</Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  body: { gap: spacing.md, paddingBottom: spacing.xxl },
  help: { ...font.caption, color: colors.textSub },
  errorBox: { gap: spacing.sm },
  errorText: { ...font.body, color: colors.text },
  empty: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl },
  emptyTitle: { ...font.bodyStrong, color: colors.text },
  row: {
    minHeight: 52,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.card,
  },
  rowText: { ...font.body, flex: 1, color: colors.text },
  editBox: {
    padding: spacing.md,
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.accent,
    borderRadius: radius.md,
    backgroundColor: colors.card,
  },
  input: { ...font.body, minHeight: 72, padding: spacing.md, borderRadius: radius.sm, backgroundColor: colors.surface, color: colors.text, textAlignVertical: "top" },
  editActions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm },
  editButton: { minHeight: 44, minWidth: 72, paddingHorizontal: spacing.lg, alignItems: "center", justifyContent: "center", borderRadius: radius.sm },
  saveButton: { backgroundColor: colors.dark },
  disabled: { opacity: 0.5 },
  cancelText: { ...font.bodyStrong, color: colors.textSub },
  saveText: { ...font.bodyStrong, color: colors.onDark },
  remove: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  removeAll: { alignSelf: "center", minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.lg },
  removeAllText: { ...font.bodyStrong, color: colors.textSub },
});
