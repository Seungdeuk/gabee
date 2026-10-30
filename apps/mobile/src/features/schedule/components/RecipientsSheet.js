import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { sheetGuide, splitChips } from "../recipients_edit";
import BottomSheet from "./BottomSheet";
import FilterChip from "./FilterChip";

const toggle = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

/**
 * 보낸 부탁의 "받는 사람 바꾸기" 시트. 지금 받는 사람이 처음부터 선택돼 있고, 위 줄에는 수락한 사람, 아래 줄에는 나머지 칩이 있다.
 * 고른 사람에 따라 안내가 바뀌고, 아무도 안 골랐거나 바뀐 게 없으면 저장할 수 없다. 열 때마다 새로 만들어 쓴다(고른 값이 지금 받는 사람으로 시작).
 * @param {{ candidates: { id: string, name: string }[], current: string[], replies: Record<string, "accepted" | "declined">,
 *   saving?: boolean, onClose: () => void, onSave: (toIds: string[]) => void }} props
 */
export default function RecipientsSheet({ candidates, current, replies, saving = false, onClose, onSave }) {
  const [draft, setDraft] = useState(current);
  const { accepted, others } = splitChips(candidates, current, replies);
  const { message, canSave } = sheetGuide(current, replies, draft);
  const disabled = !canSave || saving;
  const chip = (m) => <FilterChip key={m.id} label={m.name} selected={draft.includes(m.id)} onPress={() => setDraft(toggle(draft, m.id))} />;

  return (
    <BottomSheet visible onClose={onClose}>
      <Text style={styles.title}>받는 사람 바꾸기</Text>
      <View style={styles.chips}>
        {accepted.length > 0 ? (
          <View style={styles.line}>
            <View style={styles.tag}>
              <Text style={styles.tagText}>수락</Text>
            </View>
            {accepted.map(chip)}
          </View>
        ) : null}
        {others.length > 0 ? <View style={styles.line}>{others.map(chip)}</View> : null}
      </View>
      <Text style={styles.hint}>내용은 바꿀 수 없어요. 내용을 바꾸려면 부탁을 취소하고 다시 보내 주세요</Text>
      {message ? (
        <View style={styles.notice} accessibilityRole="alert">
          <Text style={styles.noticeText}>{message}</Text>
        </View>
      ) : null}
      <View style={styles.row}>
        <Pressable onPress={onClose} style={[styles.button, styles.close]} accessibilityRole="button">
          <Text style={styles.closeText}>닫기</Text>
        </Pressable>
        <Pressable
          onPress={() => onSave(draft)}
          disabled={disabled}
          style={[styles.button, styles.save, disabled && styles.disabled]}
          accessibilityRole="button"
          accessibilityState={{ disabled }}
        >
          <Text style={styles.saveText}>저장</Text>
        </Pressable>
      </View>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  chips: { gap: 8, marginTop: 4 },
  line: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 6 },
  tag: { paddingHorizontal: 10, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: colors.success },
  tagText: { ...font.caption, lineHeight: 18, fontWeight: "700", color: colors.onDark, includeFontPadding: false },
  hint: { ...font.caption, color: colors.textMuted },
  notice: { padding: 10, borderRadius: radius.button, backgroundColor: colors.surfaceStrong },
  noticeText: { fontSize: 14, color: colors.text },
  row: { flexDirection: "row", gap: spacing.sm, marginTop: 6 },
  button: { flex: 1, minHeight: 48, alignItems: "center", justifyContent: "center", borderRadius: radius.button },
  close: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  closeText: { fontSize: 15, fontWeight: "500", color: colors.text },
  save: { backgroundColor: colors.peach },
  saveText: { fontSize: 15, fontWeight: "700", color: colors.text },
  disabled: { opacity: 0.45 },
});
