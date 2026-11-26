import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { PHOTO_SAVE_LABEL } from "../fileUtils";
import { LIBRARY_BUTTON_LABEL, LIBRARY_DONE_LABEL, LIBRARY_SAVING_LABEL, removeLabel } from "../saveToLibrary";

/**
 * 사진 전체 화면 보기. 원본(attachment.url)을 화면 안에 비율대로 맞춰 보여 주고, 닫기 버튼(또는 뒤로 가기)으로 닫는다.
 * onSaveToLibrary 가 있으면(가족 전체방의 사진) "문서로 저장" 버튼으로 가족 공유 문서함에 직접 넣고, 저장 중·저장함·결과 문구는 library* 로 보여 준다.
 * onRemoveFromLibrary 가 있으면(이미 문서함에 있는 가족 전체방 사진) "문서함에서 빼기" 버튼을 보인다. 상태(확인 단계·빼는 중·뺌)는 removeState 로 받고 결과 문구는 libraryNotice 에 보인다.
 * onSaveToDevice 가 있으면 "사진첩에 저장" 버튼으로 기기 사진첩(갤러리)에 저장하고(저장 중·결과 문구는 deviceSaving·deviceNotice), 버튼들은 한 줄에 나란히(좁으면 줄바꿈) 놓인다.
 * @param {{ path: string, visible: boolean, onClose: () => void, onSaveToLibrary?: () => void, librarySaving?: boolean, libraryDone?: boolean, libraryNotice?: string, onRemoveFromLibrary?: () => void, removeState?: { confirming?: boolean, removing?: boolean, removed?: boolean }, onSaveToDevice?: () => void, deviceSaving?: boolean, deviceNotice?: string }} props path 는 서버가 준 attachment.url
 */
export default function PhotoViewer({ path, visible, onClose, onSaveToLibrary, librarySaving = false, libraryDone = false, libraryNotice = "", onRemoveFromLibrary, removeState = {}, onSaveToDevice, deviceSaving = false, deviceNotice = "" }) {
  const removeBusy = Boolean(removeState.removing || removeState.removed);
  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <SafeAreaView style={styles.safe}>
        <View style={styles.bar}>
          <IconButton name="close" label="사진 닫기" onPress={onClose} color={colors.onDark} />
        </View>
        <AuthImage path={path} contentFit="contain" style={styles.image} accessibilityLabel="사진" />
        {onSaveToLibrary || onSaveToDevice || onRemoveFromLibrary ? (
          <View style={styles.footer}>
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
              {onRemoveFromLibrary ? (
                <Pressable
                  onPress={onRemoveFromLibrary}
                  disabled={removeBusy}
                  accessibilityRole="button"
                  accessibilityLabel={removeLabel(removeState)}
                  accessibilityState={{ disabled: removeBusy }}
                  style={({ pressed }) => [styles.record, (pressed || removeBusy) && styles.pressed]}
                  testID="chat-photo-remove-library"
                >
                  <Ionicons name={removeState.removed ? "checkmark-circle-outline" : "remove-circle-outline"} size={18} color={colors.text} />
                  <Text style={styles.recordText}>{removeLabel(removeState)}</Text>
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
});
