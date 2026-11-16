import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { PHOTO_SAVE_LABEL } from "../fileUtils";
import { LIBRARY_BUTTON_LABEL, LIBRARY_DONE_LABEL, LIBRARY_SAVING_LABEL } from "../saveToLibrary";

/**
 * 사진 전체 화면 보기. 원본(attachment.url)을 화면 안에 비율대로 맞춰 보여 주고, 닫기 버튼(또는 뒤로 가기)으로 닫는다.
 * onSaveToLibrary 가 있으면(가족 전체방의 사진) "문서로 저장" 버튼으로 가족 공유 문서함에 직접 넣고, 저장 중·저장함·결과 문구는 library* 로 보여 준다.
 * onSaveToDevice 가 있으면 "사진첩에 저장" 버튼으로 기기 사진첩(갤러리)에 저장하고(저장 중·결과 문구는 deviceSaving·deviceNotice), 두 버튼은 한 줄에 나란히(좁으면 줄바꿈) 놓인다.
 * caption 이 있으면 사진 아래에 한 줄로 보이고(타임라인의 날짜), actions 의 버튼들이 문서·사진첩 저장 버튼 위에 한 줄로 놓인다(각 버튼: key·label·icon(Ionicons 이름)·onPress·disabled).
 * actionNotice 는 그 버튼들의 결과·오류 문구다.
 * @param {{ path: string, visible: boolean, onClose: () => void, onSaveToLibrary?: () => void, librarySaving?: boolean, libraryDone?: boolean, libraryNotice?: string, onSaveToDevice?: () => void, deviceSaving?: boolean, deviceNotice?: string, caption?: string, actions?: { key: string, label: string, icon: string, onPress: () => void, disabled?: boolean }[], actionNotice?: string }} props path 는 서버가 준 attachment.url
 */
export default function PhotoViewer({ path, visible, onClose, onSaveToLibrary, librarySaving = false, libraryDone = false, libraryNotice = "", onSaveToDevice, deviceSaving = false, deviceNotice = "", caption = "", actions = [], actionNotice = "" }) {
  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <SafeAreaView style={styles.safe}>
        <View style={styles.bar}>
          <IconButton name="close" label="사진 닫기" onPress={onClose} color={colors.onDark} />
        </View>
        <AuthImage path={path} contentFit="contain" style={styles.image} accessibilityLabel="사진" />
        {onSaveToLibrary || onSaveToDevice || actions.length > 0 || caption ? (
          <View style={styles.footer}>
            {caption ? <Text style={styles.caption}>{caption}</Text> : null}
            {actions.length > 0 ? (
              <View style={styles.buttons}>
                {actions.map((action) => (
                  <Pressable
                    key={action.key}
                    onPress={action.onPress}
                    disabled={action.disabled}
                    accessibilityRole="button"
                    accessibilityLabel={action.label}
                    accessibilityState={{ disabled: !!action.disabled }}
                    style={({ pressed }) => [styles.record, (pressed || action.disabled) && styles.pressed]}
                    testID={`photo-viewer-${action.key}`}
                  >
                    <Ionicons name={action.icon} size={18} color={colors.text} />
                    <Text style={styles.recordText}>{action.label}</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
            {actionNotice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {actionNotice}
              </Text>
            ) : null}
            <View style={styles.buttons}>
              {onSaveToDevice ? (
                <Pressable
                  onPress={onSaveToDevice}
                  disabled={deviceSaving}
                  accessibilityRole="button"
                  accessibilityLabel={PHOTO_SAVE_LABEL}
                  accessibilityState={{ disabled: deviceSaving }}
                  style={({ pressed }) => [styles.record, (pressed || deviceSaving) && styles.pressed]}
                  testID="chat-photo-save-device"
                >
                  <Ionicons name="download-outline" size={18} color={colors.text} />
                  <Text style={styles.recordText}>{deviceSaving ? "저장하는 중…" : PHOTO_SAVE_LABEL}</Text>
                </Pressable>
              ) : null}
              {onSaveToLibrary ? (
                <Pressable
                  onPress={onSaveToLibrary}
                  disabled={librarySaving || libraryDone}
                  accessibilityRole="button"
                  accessibilityLabel={LIBRARY_BUTTON_LABEL}
                  accessibilityState={{ disabled: librarySaving || libraryDone }}
                  style={({ pressed }) => [styles.record, (pressed || librarySaving || libraryDone) && styles.pressed]}
                  testID="chat-photo-save-library"
                >
                  <Ionicons name={libraryDone ? "checkmark-circle-outline" : "document-text-outline"} size={18} color={colors.text} />
                  <Text style={styles.recordText}>{librarySaving ? LIBRARY_SAVING_LABEL : libraryDone ? LIBRARY_DONE_LABEL : LIBRARY_BUTTON_LABEL}</Text>
                </Pressable>
              ) : null}
            </View>
            {deviceNotice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {deviceNotice}
              </Text>
            ) : null}
            {libraryNotice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {libraryNotice}
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
  buttons: { flexDirection: "row", flexWrap: "wrap", justifyContent: "center", gap: spacing.sm },
  record: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  pressed: { opacity: 0.7 },
  recordText: { ...font.bodyStrong, color: colors.text },
  notice: { ...font.caption, color: colors.onDark, textAlign: "center" },
  caption: { ...font.caption, color: colors.onDark, textAlign: "center" },
});
