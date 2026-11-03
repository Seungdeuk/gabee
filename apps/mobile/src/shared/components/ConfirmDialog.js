import { Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 화면 가운데 확인 팝업. 되돌릴 수 없는 동작(삭제, 가족 나가기 등)을 확인할 때 쓰고, 하단 시트(날짜·시간 선택)와 구분된다.
 * 안전한 취소를 왼쪽에, 위험한 확인(삭제·나가기)을 오른쪽에 오류 색으로 둔다.
 * @param {{ visible: boolean, title: string, message?: string, cancelLabel?: string, confirmLabel: string, onCancel: () => void, onConfirm: () => void }} props
 * @returns {import("react").ReactElement}
 */
export default function ConfirmDialog({ visible, title, message, cancelLabel = "취소", confirmLabel, onCancel, onConfirm }) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.backdrop} onPress={onCancel} accessibilityLabel="닫기">
        <Pressable style={styles.dialog} onPress={() => {}} accessibilityRole="alert">
          <Text style={styles.title}>{title}</Text>
          {message ? <Text style={styles.message}>{message}</Text> : null}
          <View style={styles.row}>
            <Pressable onPress={onCancel} style={[styles.button, styles.cancel]} accessibilityRole="button">
              <Text style={styles.cancelText}>{cancelLabel}</Text>
            </Pressable>
            <Pressable onPress={onConfirm} style={[styles.button, styles.danger]} accessibilityRole="button">
              <Text style={styles.dangerText}>{confirmLabel}</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xxl, backgroundColor: "rgba(85,59,41,0.35)" },
  dialog: { width: "100%", gap: 10, padding: 20, backgroundColor: colors.card, borderRadius: radius.card },
  title: { ...font.title, color: colors.text },
  message: { ...font.body, color: colors.textMuted },
  row: { flexDirection: "row", gap: spacing.sm, marginTop: 6 },
  button: { flex: 1, minHeight: 48, alignItems: "center", justifyContent: "center", borderRadius: radius.button },
  cancel: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  cancelText: { fontSize: 15, fontWeight: "500", color: colors.text },
  danger: { backgroundColor: colors.danger },
  dangerText: { fontSize: 15, fontWeight: "700", color: colors.onDark },
});
