import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import TodoComposer from "../components/TodoComposer";
import TodoEditModal from "../components/TodoEditModal";
import { originalRoute } from "../boardUtils";
import TodoRow from "../components/TodoRow";
import useTodoOrigins from "../useTodoOrigins";
import useTodos from "../useTodos";

/**
 * 가족 할 일 화면: 안 끝난 일 목록, 접이식 완료한 일, 하단 추가줄. 화면이 보일 때와 당겨서 새로고침할 때만 불러온다(폴링 없음).
 */
export default function FamilyTodosScreen() {
  const router = useRouter();
  const todos = useTodos();
  const origins = useTodoOrigins(); // 대화에서 등록한 할 일의 원본 메시지
  const openOrigin = (todo) => router.push(originalRoute({ messageId: origins[todo.id] }));
  const [editing, setEditing] = useState(null); // 고치는 중인 할 일 id
  const [notice, setNotice] = useState(""); // 완료·되돌리기 실패 안내
  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));
  const editTarget = editing ? [...todos.open, ...todos.done].find((t) => t.id === editing) : null;

  const toggle = async (todo) => {
    setNotice("");
    const message = await todos.toggleDone(todo);
    if (message) setNotice(message);
  };

  let body;
  if (todos.status === "loading") {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </View>
    );
  } else if (todos.status === "none") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyTitle}>가족을 먼저 만들어 주세요</Text>
        <Button label="가족 만들기 · 참여하기" onPress={() => router.push("/family")} />
      </View>
    );
  } else if (todos.status === "error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{todos.error}</Text>
        <Button label="다시 시도" onPress={todos.reload} />
      </View>
    );
  } else {
    body = (
      <>
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={todos.refreshing} onRefresh={todos.refresh} tintColor={colors.accent} />}
        >
          {notice || todos.info || todos.error ? (
            <Text style={styles.error} accessibilityRole="alert">
              {notice || todos.info || todos.error}
            </Text>
          ) : null}
          {todos.open.length === 0 ? (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>남은 할 일이 없어요</Text>
              <Text style={styles.emptyText}>아래에서 가족과 나눌 할 일을 적어 보세요.</Text>
            </View>
          ) : (
            todos.open.map((t) => <TodoRow key={t.id} todo={t} members={todos.members} onToggle={() => toggle(t)} onEdit={() => setEditing(t.id)} onOpenOrigin={origins[t.id] ? () => openOrigin(t) : undefined} />)
          )}

          <Pressable
            onPress={() => todos.setDoneOpen(!todos.doneOpen)}
            accessibilityRole="button"
            accessibilityState={{ expanded: todos.doneOpen }}
            style={styles.doneHead}
          >
            <Text style={styles.doneTitle}>{todos.doneLoaded ? `완료한 일 ${todos.done.length}` : "완료한 일"}</Text>
            <Ionicons name={todos.doneOpen ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
          </Pressable>
          {todos.doneOpen
            ? todos.doneLoaded
              ? todos.done.length === 0
                ? <Text style={styles.emptyText}>아직 끝낸 일이 없어요</Text>
                : todos.done.map((t) => <TodoRow key={t.id} todo={t} members={todos.members} onToggle={() => toggle(t)} onEdit={() => setEditing(t.id)} onOpenOrigin={origins[t.id] ? () => openOrigin(t) : undefined} />)
              : <ActivityIndicator color={colors.accent} accessibilityLabel="완료한 일을 불러오는 중" />
            : null}
        </ScrollView>
        <TodoComposer members={todos.members} onAdd={todos.add} />
        {editTarget ? (
          <TodoEditModal
            key={editTarget.id}
            todo={editTarget}
            members={todos.members}
            onClose={() => setEditing(null)}
            onSave={(patch) => todos.edit(editTarget.id, patch)}
            onDelete={() => todos.remove(editTarget.id)}
          />
        ) : null}
      </>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <Text style={styles.barTitle} accessibilityRole="header">
          가족 할 일
        </Text>
      </View>
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        {body}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  bar: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.divider },
  barTitle: { ...font.cardTitle, color: colors.text, flex: 1 },
  content: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.xs },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  empty: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl },
  emptyTitle: { ...font.cardTitle, color: colors.text, textAlign: "center" },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  error: { ...font.caption, color: colors.danger, paddingVertical: spacing.xs },
  doneHead: { minHeight: 44, flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.lg },
  doneTitle: { ...font.bodyStrong, color: colors.textSub },
});
