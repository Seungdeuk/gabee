import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { assigneeName, dueLabel } from "../todoUtils";

/**
 * 할 일 한 줄: 왼쪽 체크 원(완료·되돌리기), 제목, 담당자와 기한. 줄을 누르면 고치기 창이 열린다.
 * @param {{ todo: { id: string, title: string, done: boolean, assignee_id: string | null, due_date: string | null }, members: { id: string, name: string }[], onToggle: () => void, onEdit: () => void }} props
 */
export default function TodoRow({ todo, members, onToggle, onEdit }) {
  const who = assigneeName(members, todo.assignee_id);
  const due = todo.due_date ? dueLabel(todo.due_date) : null;
  const meta = [who && `담당 ${who}`].filter(Boolean).join(" · ");
  return (
    <View style={styles.row}>
      <Pressable
        onPress={onToggle}
        hitSlop={spacing.sm}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: todo.done }}
        accessibilityLabel={todo.done ? `${todo.title} 다시 진행으로 표시` : `${todo.title} 완료로 표시`}
        style={styles.checkBox}
      >
        <Ionicons name={todo.done ? "checkmark-circle" : "ellipse-outline"} size={28} color={todo.done ? colors.success : colors.textMuted} />
      </Pressable>
      <Pressable onPress={onEdit} accessibilityRole="button" accessibilityLabel={`할 일 고치기: ${todo.title}`} style={({ pressed }) => [styles.body, pressed && styles.pressed]}>
        <Text style={[styles.title, todo.done && styles.titleDone]} numberOfLines={2}>
          {todo.title}
        </Text>
        {meta || due ? (
          <View style={styles.meta}>
            {meta ? <Text style={styles.metaText}>{meta}</Text> : null}
            {due && !todo.done ? <Text style={[styles.metaText, due.overdue && styles.overdue]}>{due.text}</Text> : null}
            {due && todo.done ? <Text style={styles.metaText}>{due.text.replace(/^지남 · /, "")}</Text> : null}
          </View>
        ) : null}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  checkBox: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  body: { flex: 1, minHeight: 44, justifyContent: "center", gap: spacing.xs, borderRadius: radius.md },
  pressed: { backgroundColor: colors.surface },
  title: { ...font.body, color: colors.text },
  titleDone: { color: colors.textMuted, textDecorationLine: "line-through" },
  meta: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  metaText: { ...font.caption, color: colors.textMuted },
  overdue: { color: colors.danger, fontFamily: font.bodyStrong.fontFamily },
});
