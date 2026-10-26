import { Ionicons } from "@expo/vector-icons";
import { useContext } from "react";
import { Modal, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaInsetsContext } from "react-native-safe-area-context";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 메시지를 길게 눌렀을 때 아래에서 올라오는 작은 메뉴(Modal 이라 웹에서도 같다). "복사"와 "공지로 고정 / 고정 해제", "닫기".
 * message 가 없으면 닫힌 상태다. 고정 항목은 서버에 저장된 텍스트 메시지에만 열리므로(호출하는 쪽이 확인) 여기서는 그대로 보여 준다.
 * @param {{ message: { id: number|string, text: string } | null, pinned: boolean, onClose: () => void, onCopy: () => void, onPin: () => void, onUnpin: () => void }} props
 */
const FALLBACK_BOTTOM = Platform.OS === "ios" ? 34 : 0; // 안전 영역 정보가 없을 때의 기본값

export default function MessageActionSheet({ message, pinned, onClose, onCopy, onPin, onUnpin }) {
  const insets = useContext(SafeAreaInsetsContext); // Modal 안에서 값이 없을 수 있어 훅 대신 context 를 직접 읽는다
  const bottom = insets?.bottom ?? FALLBACK_BOTTOM;
  const items = [
    { key: "copy", icon: "copy-outline", label: "복사", onPress: onCopy },
    pinned ? { key: "unpin", icon: "pin-outline", label: "고정 해제", onPress: onUnpin } : { key: "pin", icon: "pin", label: "공지로 고정", onPress: onPin },
  ];
  return (
    <Modal visible={message != null} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="메뉴 닫기" />
        <View style={[styles.sheet, { paddingBottom: spacing.sm + bottom }]}>
          {items.map((item) => (
            <Pressable key={item.key} onPress={item.onPress} accessibilityRole="button" accessibilityLabel={item.label} style={({ pressed }) => [styles.item, pressed && styles.pressed]}>
              <Ionicons name={item.icon} size={20} color={colors.textSub} />
              <Text style={styles.label}>{item.label}</Text>
            </Pressable>
          ))}
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="닫기" style={({ pressed }) => [styles.item, styles.close, pressed && styles.pressed]}>
            <Text style={styles.closeLabel}>닫기</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.dark, opacity: 0.4 },
  sheet: { backgroundColor: colors.background, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card, paddingVertical: spacing.sm },
  item: { minHeight: 52, flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.xl },
  pressed: { backgroundColor: colors.surface },
  label: { ...font.bodyStrong, color: colors.text },
  close: { justifyContent: "center", borderTopWidth: 1, borderTopColor: colors.divider },
  closeLabel: { ...font.bodyStrong, color: colors.textMuted },
});
