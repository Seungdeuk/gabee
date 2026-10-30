import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, font, radius, spacing } from "@/theme";

import { PLUS_MENU_ITEMS } from "../fileUtils";

/**
 * 입력줄의 + 버튼이 여는, 아래에서 올라오는 메뉴 시트: 사진 · 파일 · 일정 · 정산 · 안부(아이콘+이름 한 줄씩). 바깥을 누르면 닫힌다.
 * @param {{ visible: boolean, onClose: () => void, onSelect: (key: string) => void }} props onSelect 는 항목 key(photo/file/schedule/settle/safety)를 받는다
 */
export default function PlusSheet({ visible, onClose, onSelect }) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="메뉴 닫기" />
        <SafeAreaView edges={["bottom"]} style={styles.sheet} accessibilityViewIsModal>
          <View style={styles.handle} />
          {PLUS_MENU_ITEMS.map((item) => (
            <Pressable
              key={item.key}
              onPress={() => onSelect(item.key)}
              accessibilityRole="button"
              accessibilityLabel={item.label}
              style={({ pressed }) => [styles.item, pressed && styles.pressed]}
            >
              <Ionicons name={item.icon} size={22} color={colors.textSub} />
              <Text style={styles.label}>{item.label}</Text>
            </Pressable>
          ))}
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.dark, opacity: 0.3 },
  sheet: { backgroundColor: colors.card, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  handle: { alignSelf: "center", width: 36, height: 4, borderRadius: radius.pill, backgroundColor: colors.divider, marginVertical: spacing.sm },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 52, paddingHorizontal: spacing.xs, borderRadius: radius.md },
  pressed: { backgroundColor: colors.surface },
  label: { ...font.body, color: colors.text },
});
