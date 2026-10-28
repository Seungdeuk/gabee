import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { RECORD_BUTTON_LABEL } from "../saveToRecord";

/**
 * 사진 전체 화면 보기. 원본(attachment.url)을 화면 안에 비율대로 맞춰 보여 주고, 닫기 버튼(또는 뒤로 가기)으로 닫는다.
 * onSaveToRecord 가 있으면(가족 전체방의 사진) 아래에 "가비 기록에 저장" 버튼을 보이고, 눌러서 저장하는 동안·저장한 뒤의 상태와 결과 문구를 보여 준다.
 * @param {{ path: string, visible: boolean, onClose: () => void, onSaveToRecord?: () => void, recordSaving?: boolean, recordDone?: boolean, recordNotice?: string }} props path 는 서버가 준 attachment.url
 */
export default function PhotoViewer({ path, visible, onClose, onSaveToRecord, recordSaving = false, recordDone = false, recordNotice = "" }) {
  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <SafeAreaView style={styles.safe}>
        <View style={styles.bar}>
          <IconButton name="close" label="사진 닫기" onPress={onClose} color={colors.onDark} />
        </View>
        <AuthImage path={path} contentFit="contain" style={styles.image} accessibilityLabel="사진" />
        {onSaveToRecord ? (
          <View style={styles.footer}>
            <Pressable
              onPress={onSaveToRecord}
              disabled={recordSaving || recordDone}
              accessibilityRole="button"
              accessibilityLabel={RECORD_BUTTON_LABEL}
              accessibilityState={{ disabled: recordSaving || recordDone }}
              style={({ pressed }) => [styles.record, (pressed || recordSaving || recordDone) && styles.pressed]}
              testID="chat-photo-save-record"
            >
              <Ionicons name={recordDone ? "checkmark-circle-outline" : "sparkles-outline"} size={18} color={colors.text} />
              <Text style={styles.recordText}>{recordSaving ? "저장하는 중…" : recordDone ? "저장했어요" : RECORD_BUTTON_LABEL}</Text>
            </Pressable>
            {recordNotice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {recordNotice}
              </Text>
            ) : null}
          </View>
        ) : null}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.dark },
  bar: { alignItems: "flex-end", paddingHorizontal: spacing.sm },
  image: { flex: 1, backgroundColor: colors.dark },
  footer: { alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  record: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  pressed: { opacity: 0.7 },
  recordText: { ...font.bodyStrong, color: colors.text },
  notice: { ...font.caption, color: colors.onDark, textAlign: "center" },
});
