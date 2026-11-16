import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import {
  ACK_LABEL,
  CONFIRMING_LABEL,
  CONFIRM_LABEL,
  DOC_CHECKING,
  DOC_SAVE_HINT,
  LATER_LABEL,
  SHEET_NOTICE_BODY,
  SHEET_NOTICE_TITLE,
  canConfirm,
  statusLabel,
} from "../photoChecks";
import { LIBRARY_BUTTON_LABEL, LIBRARY_SAVING_LABEL } from "../saveToLibrary";

/**
 * 사진 한 장을 일반 사진으로 확인하는 바닥 시트. 안내 문구를 읽고 확인란을 체크해야만 "일반 사진이에요"가 켜진다(체크 전에는 눌러도 아무 일도 없다).
 * 문서나 서류가 찍힌 사진은 "문서로 저장"으로 문서함에 넣는다(문서로 판단된 사진은 타임라인에 나오지 않는다). 처리 중에는 두 버튼이 모두 잠긴다(두 번 눌러도 한 번만 보낸다).
 * docState: 이 사진의 문서함 저장 진행("checking" 등록 확인 중, "not_registered" 확인했는데 아직 없음 → 다시 저장만 보인다, 그 밖에는 없음).
 * @param {{ item: { attachment_id: string, thumb_url: string, status: string } | null, acknowledged: boolean, busy: null | "confirm" | "doc", docState?: "checking" | "not_registered" | null, message: string, onToggleAck: () => void, onConfirm: () => void, onSaveDocument: () => void, onClose: () => void }} props
 */
export default function PhotoReviewSheet({ item, acknowledged, busy, docState = null, message, onToggleAck, onConfirm, onSaveDocument, onClose }) {
  const locked = busy != null || docState === "checking";
  const retryOnly = docState === "not_registered"; // 이미 문서로 저장을 요청한 사진: 일반 사진 확인은 막혀 있으니 다시 저장만 보인다
  return (
    <Modal visible={item != null} transparent animationType="slide" onRequestClose={() => !locked && onClose()} statusBarTranslucent>
      <View style={styles.root}>
        <Pressable style={styles.scrim} onPress={() => !locked && onClose()} accessibilityRole="button" accessibilityLabel="닫기" />
        <SafeAreaView style={styles.sheet} edges={["bottom"]}>
          {item ? (
            <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
              <View style={styles.previewRow}>
                <AuthImage path={item.thumb_url} style={styles.preview} contentFit="cover" accessibilityLabel="확인할 사진" />
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>{statusLabel(item.status)}</Text>
                </View>
              </View>
              {retryOnly ? null : (
                <>
                  <Text style={styles.title} accessibilityRole="header">
                    {SHEET_NOTICE_TITLE}
                  </Text>
                  <Text style={styles.body}>{SHEET_NOTICE_BODY}</Text>
                  <Pressable
                    onPress={onToggleAck}
                    disabled={locked}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: acknowledged, disabled: locked }}
                    accessibilityLabel={ACK_LABEL}
                    style={styles.ackRow}
                  >
                    <Ionicons name={acknowledged ? "checkbox" : "square-outline"} size={26} color={acknowledged ? colors.accent : colors.textMuted} />
                    <Text style={styles.ackText}>{ACK_LABEL}</Text>
                  </Pressable>
                </>
              )}
              {message ? (
                <Text style={styles.message} accessibilityLiveRegion="polite">
                  {message}
                </Text>
              ) : null}
              {docState === "checking" ? (
                <View style={styles.checking} accessibilityLiveRegion="polite">
                  <ActivityIndicator color={colors.accent} />
                  <Text style={styles.checkingText}>{DOC_CHECKING}</Text>
                </View>
              ) : null}
              <View style={styles.actions}>
                {retryOnly ? null : (
                  <Button
                    label={busy === "confirm" ? CONFIRMING_LABEL : CONFIRM_LABEL}
                    onPress={onConfirm}
                    disabled={!canConfirm({ acknowledged, busy: locked })}
                    testID="photo-review-confirm"
                  />
                )}
                {retryOnly ? null : <Text style={styles.hint}>{DOC_SAVE_HINT}</Text>}
                <Button
                  label={busy === "doc" ? LIBRARY_SAVING_LABEL : retryOnly ? "다시 저장" : LIBRARY_BUTTON_LABEL}
                  variant="secondary"
                  onPress={onSaveDocument}
                  disabled={locked}
                  testID="photo-review-document"
                />
                <Button label={LATER_LABEL} variant="ghost" onPress={onClose} disabled={locked} testID="photo-review-later" />
              </View>
            </ScrollView>
          ) : null}
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  scrim: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.dark, opacity: 0.4 },
  sheet: { maxHeight: "92%", backgroundColor: colors.background, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card },
  content: { padding: spacing.lg, gap: spacing.md },
  previewRow: { alignItems: "center" },
  preview: { width: "100%", aspectRatio: 1, maxHeight: 280, borderRadius: radius.card },
  badge: { position: "absolute", top: spacing.sm, left: spacing.sm, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  badgeText: { ...font.tab, color: colors.text },
  title: { ...font.cardTitle, color: colors.text },
  body: { ...font.body, color: colors.textSub },
  ackRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 48, paddingVertical: spacing.xs },
  ackText: { ...font.bodyStrong, color: colors.text, flex: 1 },
  message: { ...font.body, color: colors.danger },
  checking: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  checkingText: { ...font.caption, color: colors.textSub },
  actions: { gap: spacing.sm, marginTop: spacing.sm },
  hint: { ...font.caption, color: colors.textMuted },
});
