import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 모음에서 사진 전체 화면 보기: 원본, 닫기, 보낸 사람·시각, 저장 버튼. 저장 결과는 아래에 짧게 알린다.
 * @param {{ item: { url: string } | null, caption: string, visible: boolean, onClose: () => void, onSave: () => void, saving?: boolean, notice?: string }} props
 */
export default function MediaViewer({ item, caption, visible, onClose, onSave, saving = false, notice = "" }) {
  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <SafeAreaView style={styles.safe}>
        <View style={styles.bar}>
          <IconButton name="close" label="사진 닫기" onPress={onClose} color={colors.onDark} />
        </View>
        <AuthImage path={item?.url} contentFit="contain" style={styles.image} accessibilityLabel="사진" />
        <View style={styles.footer}>
          <Text style={styles.caption} numberOfLines={2}>
            {caption}
          </Text>
          <Pressable
            onPress={onSave}
            disabled={saving}
            accessibilityRole="button"
            accessibilityLabel="사진 저장"
            style={({ pressed }) => [styles.save, (pressed || saving) && styles.pressed]}
          >
            <Ionicons name="download-outline" size={18} color={colors.text} />
            <Text style={styles.saveText}>{saving ? "저장 중…" : "저장"}</Text>
          </Pressable>
        </View>
        {notice ? (
          <Text style={styles.notice} accessibilityLiveRegion="polite">
            {notice}
          </Text>
        ) : null}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.dark },
  bar: { alignItems: "flex-end", paddingHorizontal: spacing.sm },
  image: { flex: 1, backgroundColor: colors.dark },
  footer: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  caption: { flex: 1, ...font.caption, color: colors.onDark },
  save: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  pressed: { opacity: 0.7 },
  saveText: { ...font.bodyStrong, color: colors.text },
  notice: { ...font.caption, color: colors.onDark, textAlign: "center", paddingBottom: spacing.md },
});
