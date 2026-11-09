import { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 누르면 목록이 열리고 항목을 고르면 닫히는 단순한 드롭다운(RN Modal). 바깥(투명 배경)을 누르거나 안드로이드 뒤로 가기로 닫는다.
 * @param {{
 *   value: number | string,
 *   options: { value: number | string, label: string }[],
 *   onChange: (value: number | string) => void,
 *   label: string,
 *   display?: string,
 *   testID?: string,
 * }} props label 은 접근성 라벨("시작 시"), display 는 목록에 없는 값일 때 칸에 보일 글자
 * @returns {JSX.Element}
 */
export default function Dropdown({ value, options, onChange, label, display, testID }) {
  const [open, setOpen] = useState(false);
  const shown = options.find((o) => o.value === value)?.label ?? display ?? String(value);

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label} ${shown}`}
        onPress={() => setOpen(true)}
        style={styles.box}
        testID={testID}
      >
        <Text style={styles.boxText}>{shown}</Text>
        <Text style={styles.caret}>▾</Text>
      </Pressable>
      <Modal transparent visible={open} animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)} accessibilityLabel="닫기">
          <View style={styles.sheet}>
            <Text style={styles.title}>{label}</Text>
            <ScrollView>
              {options.map((o) => {
                const selected = o.value === value;
                return (
                  <Pressable
                    key={String(o.value)}
                    accessibilityRole="button"
                    accessibilityLabel={`${label} ${o.label}`}
                    accessibilityState={{ selected }}
                    onPress={() => {
                      setOpen(false);
                      onChange(o.value);
                    }}
                    style={[styles.item, selected && styles.itemSelected]}
                  >
                    <Text style={[styles.itemText, selected && styles.itemTextSelected]}>{o.label}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  box: {
    minHeight: 44,
    minWidth: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  boxText: { ...font.bodyStrong, color: colors.text },
  caret: { ...font.caption, color: colors.textMuted },
  backdrop: { flex: 1, backgroundColor: "rgba(85,59,41,0.35)", alignItems: "center", justifyContent: "center", padding: spacing.xl }, // ConfirmDialog 와 같은 반투명 배경(theme 에 토큰이 없다)
  sheet: { width: "60%", maxHeight: "60%", borderRadius: radius.card, backgroundColor: colors.card, paddingVertical: spacing.sm },
  title: { ...font.bodyStrong, color: colors.textMuted, textAlign: "center", paddingVertical: spacing.sm },
  item: { minHeight: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.lg },
  itemSelected: { backgroundColor: colors.surfaceStrong },
  itemText: { ...font.body, color: colors.text },
  itemTextSelected: { ...font.bodyStrong, color: colors.primaryDark },
});
