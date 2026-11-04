import { Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 메모 전문 팝업(시안 4-1). 가운데 작은 창: 습관 이름, 시각 줄, 메모 전문, 공유 상태 문구, 버튼.
 * 내 화면은 [수정][닫기](수정 왼쪽, 닫기 오른쪽). 가족 탭은 [닫기]만. 배경을 누르면 닫힌다.
 * @param {{ visible: boolean, title: string, stamp: string, note: string, shareText: string, canEdit: boolean,
 *   onClose: () => void, onEdit?: () => void }} props
 */
export default function MemoFullPopup({ visible, title, stamp, note, shareText, canEdit, onClose, onEdit }) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="닫기">
        <Pressable style={styles.card} onPress={() => {}} accessibilityRole="alert">
          <View style={styles.head}>
            <Text style={styles.title}>{title}</Text>
            <Text style={styles.stamp}>{stamp}</Text>
          </View>
          <View style={styles.box}>
            <Text style={styles.note}>{note}</Text>
          </View>
          <Text style={styles.share}>{shareText}</Text>
          <View style={styles.row}>
            {canEdit ? (
              <Pressable onPress={onEdit} style={[styles.button, styles.edit]} accessibilityRole="button" accessibilityLabel="메모 수정">
                <Text style={styles.editText}>수정</Text>
              </Pressable>
            ) : null}
            <Pressable onPress={onClose} style={[styles.button, styles.close]} accessibilityRole="button" accessibilityLabel="닫기">
              <Text style={styles.closeText}>닫기</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 24, backgroundColor: "rgba(85,59,41,0.35)" },
  card: {
    width: "100%",
    paddingTop: 26,
    paddingHorizontal: 22,
    paddingBottom: 20,
    borderRadius: 24,
    backgroundColor: colors.background,
    gap: 16,
    shadowColor: colors.text,
    shadowOpacity: 0.12,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  head: { gap: 4 },
  title: { fontSize: 21, fontWeight: "700", color: colors.text },
  stamp: { fontSize: 14, color: colors.textSub },
  // 메모 전문 박스: 옅은 노랑 바탕(colors.surface), 줄바꿈 허용
  box: { borderRadius: radius.button, backgroundColor: colors.surface, padding: spacing.lg },
  note: { ...font.body, fontSize: 17, lineHeight: 27, color: colors.text },
  share: { fontSize: 13, color: colors.textSub },
  row: { flexDirection: "row", gap: 10 },
  button: { flex: 1, height: 52, borderRadius: radius.button, alignItems: "center", justifyContent: "center" },
  close: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  closeText: { fontSize: 16, fontWeight: "700", color: colors.text },
  edit: { backgroundColor: colors.peach },
  editText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
