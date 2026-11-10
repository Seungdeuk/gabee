import { Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 데일리 체크 전용 확인 팝업(안드로이드 기본 알림창 대신). 반투명 어두운 배경, 가운데 흰 카드.
 * - 확인형(cancelLabel 있음): [취소](흰 바탕) + [확인](danger 빨강 또는 primary 복숭아).
 * - 안내형(cancelLabel 없음): [확인] 하나(복숭아).
 * 배경을 누르거나 안드로이드 뒤로가기를 누르면 취소(안내형은 확인과 같이 닫힌다).
 * @param {{ visible: boolean, title: string, body?: import("react").ReactNode, cancelLabel?: string, confirmLabel: string,
 *   tone?: "danger" | "primary", onCancel: () => void, onConfirm: () => void }} props
 */
export default function ConfirmSheet({ visible, title, body, cancelLabel, confirmLabel, tone = "primary", onCancel, onConfirm }) {
  const info = !cancelLabel;
  const dismiss = info ? onConfirm : onCancel;
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={dismiss}>
      <Pressable style={styles.backdrop} onPress={dismiss} accessibilityLabel="닫기">
        <Pressable style={styles.card} onPress={() => {}} accessibilityRole="alert">
          <Text style={styles.title}>{title}</Text>
          {body ? <View style={styles.body}>{typeof body === "string" ? <Text style={styles.bodyText}>{body}</Text> : body}</View> : null}
          <View style={styles.row}>
            {info ? null : (
              <Pressable onPress={onCancel} style={[styles.button, styles.cancel]} accessibilityRole="button" accessibilityLabel={cancelLabel}>
                <Text style={styles.cancelText}>{cancelLabel}</Text>
              </Pressable>
            )}
            <Pressable
              onPress={onConfirm}
              style={[styles.button, tone === "danger" ? styles.danger : styles.primary]}
              accessibilityRole="button"
              accessibilityLabel={confirmLabel}
            >
              <Text style={tone === "danger" ? styles.dangerText : styles.primaryText}>{confirmLabel}</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** 삭제 확인 본문: 항목 이름을 굵게 한 줄, 아래 안내 한 줄("삭제하면 되돌릴 수 없어요"). */
export function ConfirmBody({ name, note }) {
  return (
    <View style={styles.body}>
      <Text style={styles.nameText}>{name}</Text>
      {note ? <Text style={styles.bodyText}>{note}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  nameText: { fontSize: 16, fontWeight: "700", color: colors.text },
  backdrop: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 24, backgroundColor: "rgba(85,59,41,0.35)" },
  card: {
    width: "100%",
    padding: spacing.xxl,
    borderRadius: 20,
    backgroundColor: colors.card,
    gap: 12,
    shadowColor: colors.text,
    shadowOpacity: 0.12,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  title: { ...font.title, color: colors.text },
  body: { gap: 4 },
  bodyText: { fontSize: 15, lineHeight: 22, color: colors.textSub },
  row: { flexDirection: "row", gap: 10, marginTop: 6 },
  button: { flex: 1, height: 48, alignItems: "center", justifyContent: "center", borderRadius: radius.button },
  cancel: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  cancelText: { fontSize: 16, fontWeight: "700", color: colors.text },
  danger: { backgroundColor: colors.danger },
  dangerText: { fontSize: 16, fontWeight: "700", color: colors.onDark },
  primary: { backgroundColor: colors.peach },
  primaryText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
