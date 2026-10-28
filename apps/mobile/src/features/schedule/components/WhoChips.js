import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import { hiddenMembers, visibleMembers } from "../favorites";
import AnchoredPopover from "./AnchoredPopover";
import FilterChip from "./FilterChip";

const DELETE_MS = 3000; // 삭제 버튼이 저절로 사라지는 시간
const toggle = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

/**
 * "누구" 칩 줄 = 자주 쓰는 사람. 짧게 누르면 선택/해제, 길게 누르면 그 칩 위에 "삭제" 버튼이 떠서 눌러야 줄에서 빠진다(약 3초 뒤 사라짐).
 * "+ 누구" 는 그 칩 아래에 말풍선을 띄워 빠져 있는 사람을 체크하고 [확인] 하면 줄에 들어간다. 빠진 사람이 없으면 "+ 누구" 는 보이지 않는다.
 * @param {{ members: { id: string, name: string }[], hiddenIds: string[], selectedIds: string[], onToggle: (id: string) => void,
 *   onHide: (id: string) => void, onShow: (id: string) => void }} props
 */
export default function WhoChips({ members, hiddenIds, selectedIds, onToggle, onHide, onShow }) {
  const [pop, setPop] = useState(null); // { kind: "delete", id, rect } | { kind: "add", rect }
  const [checked, setChecked] = useState([]);

  const shown = visibleMembers(members, hiddenIds, selectedIds);
  const spare = hiddenMembers(members, hiddenIds, selectedIds);
  const close = () => setPop(null);
  // React Compiler 가 콜백 안의 pop.id 를 렌더 중에 미리 읽으므로, null 일 때를 막아 둔 값으로 꺼내 쓴다.
  const deleteId = pop?.kind === "delete" ? pop.id : null;

  return (
    <View style={styles.chips}>
      {shown.map((m) => (
        <FilterChip
          key={m.id}
          label={m.name}
          selected={selectedIds.includes(m.id)}
          ringed={pop?.kind === "delete" && pop.id === m.id}
          onPress={() => {
            close();
            onToggle(m.id);
          }}
          onLongPressRect={(rect) => setPop({ kind: "delete", id: m.id, rect })}
        />
      ))}
      {spare.length > 0 ? (
        <FilterChip
          label="+ 누구"
          muted
          onPressRect={(rect) => {
            setChecked([]);
            setPop({ kind: "add", rect });
          }}
        />
      ) : null}

      <AnchoredPopover
        visible={pop?.kind === "delete"}
        anchor={pop?.rect ?? null}
        onClose={close}
        width={56}
        placement="above"
        tone="dark"
        autoCloseMs={DELETE_MS}
      >
        <Pressable
          onPress={() => {
            if (deleteId !== null) onHide(deleteId);
            close();
          }}
          accessibilityRole="button"
          style={styles.delete}
        >
          <Text style={styles.deleteText}>삭제</Text>
        </Pressable>
      </AnchoredPopover>

      <AnchoredPopover visible={pop?.kind === "add"} anchor={pop?.rect ?? null} onClose={close} width={190} placement="right">
        <View style={styles.bubble}>
          <Text style={styles.title}>칩에 추가할 사람</Text>
          <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
            {spare.map((m) => {
              const on = checked.includes(m.id);
              return (
                <Pressable
                  key={m.id}
                  onPress={() => setChecked(toggle(checked, m.id))}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: on }}
                  style={styles.row}
                >
                  <View style={[styles.box, on && styles.boxOn]}>
                    {on ? <Ionicons name="checkmark" size={13} color={colors.text} /> : null}
                  </View>
                  <Text style={styles.name}>{m.name}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          <Pressable
            onPress={() => {
              checked.forEach(onShow);
              close();
            }}
            accessibilityRole="button"
            style={styles.confirm}
          >
            <Text style={styles.confirmText}>확인</Text>
          </Pressable>
        </View>
      </AnchoredPopover>
    </View>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  delete: { paddingVertical: 7, alignItems: "center" },
  deleteText: { fontSize: 13, fontWeight: "700", color: colors.onDark },
  bubble: { padding: 12, gap: 8 },
  title: { ...font.caption, color: colors.textMuted },
  list: { maxHeight: 176 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6 },
  box: {
    width: 20,
    height: 20,
    borderRadius: 6,
    borderWidth: 1.5,
    borderColor: colors.textMuted,
    alignItems: "center",
    justifyContent: "center",
  },
  boxOn: { backgroundColor: colors.peach, borderColor: colors.peach },
  name: { fontSize: 14, color: colors.text },
  confirm: { minHeight: 36, alignItems: "center", justifyContent: "center", borderRadius: 12, backgroundColor: colors.text },
  confirmText: { fontSize: 13, fontWeight: "700", color: colors.onDark },
});
