import { Ionicons } from "@expo/vector-icons";
import { Alert, FlatList, Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

const pad = (n) => String(n).padStart(2, "0");

/** 오늘이면 시각, 아니면 월/일. */
function when(ms) {
  const d = new Date(ms);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/**
 * 이전 대화 목록. 누르면 그 대화를 열고, 길게 누르면 지울지 묻는다.
 * @param {{ sessions: object[], currentId: string | null, onNew: () => void, onOpen: (id: string) => void, onDelete: (id: string) => void }} props
 */
export default function SessionList({ sessions, currentId, onNew, onOpen, onDelete }) {
  const confirmDelete = (s) =>
    Alert.alert("대화를 지울까요?", `"${s.title}" 대화가 이 폰에서 지워져요. 올린 기록은 그대로 남아요.`, [
      { text: "취소", style: "cancel" },
      { text: "지우기", style: "destructive", onPress: () => onDelete(s.id) },
    ]);

  return (
    <View style={styles.flex}>
      <Pressable onPress={onNew} accessibilityRole="button" style={styles.newBtn}>
        <Ionicons name="add" size={20} color={colors.text} />
        <Text style={styles.newText}>새 대화</Text>
      </Pressable>
      <FlatList
        data={sessions}
        keyExtractor={(s) => s.id}
        contentContainerStyle={styles.list}
        ListEmptyComponent={<Text style={styles.empty}>아직 이전 대화가 없어요. 대화하면 이 폰에 저장돼요.</Text>}
        renderItem={({ item }) => (
          <Pressable
            onPress={() => onOpen(item.id)}
            onLongPress={() => confirmDelete(item)}
            accessibilityRole="button"
            accessibilityHint="길게 누르면 지울 수 있어요"
            style={[styles.row, item.id === currentId && styles.rowOn]}
          >
            <Text style={styles.rowTitle} numberOfLines={1}>
              {item.title}
            </Text>
            <Text style={styles.rowMeta}>{when(item.updatedAt)}</Text>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  newBtn: {
    marginHorizontal: 14,
    marginBottom: 8,
    minHeight: 44,
    borderRadius: 22,
    backgroundColor: colors.peach,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
  },
  newText: { fontSize: 15, fontWeight: "600", color: colors.text },
  list: { paddingHorizontal: 8, paddingBottom: 16 },
  empty: { paddingHorizontal: 16, paddingTop: 16, fontSize: 13, lineHeight: 20, color: colors.textMuted },
  row: { minHeight: 48, paddingHorizontal: 10, borderRadius: 12, flexDirection: "row", alignItems: "center", gap: 8 },
  rowOn: { backgroundColor: colors.surface },
  rowTitle: { flex: 1, fontSize: 15, color: colors.text },
  rowMeta: { fontSize: 12, color: colors.textMuted },
});
