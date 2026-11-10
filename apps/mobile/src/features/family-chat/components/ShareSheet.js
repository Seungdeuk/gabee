import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, font, radius, spacing } from "@/theme";

import { shareSheetCopy } from "../shareUtils";

const ICON = { "약속": "calendar-outline", "할 일": "checkbox-outline", "정산": "wallet-outline" };

/**
 * 공유 카드로 보낼 항목을 고르는 아래 시트: 일정이면 내 일정·할 일(오늘 이후), 정산이면 최근 몇 달. 항목을 누르면 onPick(item) 으로 넘기고(확인창은 부모가 시트가 닫힌 뒤에 연다), "닫기" 버튼·바깥 어두운 곳·뒤로 가기·VoiceOver 탈출 동작(두 손가락 문지르기)이면 onClose 로 닫는다.
 * 불러오는 중에는 진행 표시, 오류면 문구와 "다시 시도", 항목이 없으면 빈 상태 문구를 보인다.
 * @param {{ visible: boolean, kind: "event" | "settlement" | null, status: "idle" | "loading" | "ready" | "error", items: { key: string, ref: string, title: string, line: string, badge: string }[], error?: string, onPick: (item: object) => void, onRetry: () => void, onClose: () => void }} props
 * @returns {import("react").ReactElement}
 */
export default function ShareSheet({ visible, kind, status, items, error = "", onPick, onRetry, onClose }) {
  const copy = shareSheetCopy(kind);
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="공유 시트 닫기" />
        <SafeAreaView edges={["bottom"]} style={styles.sheet} accessibilityViewIsModal onAccessibilityEscape={onClose}>
          <View style={styles.handle} />
          <View style={styles.header}>
            <Text style={styles.title}>{copy.title}</Text>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="닫기" hitSlop={spacing.sm} style={({ pressed }) => [styles.close, pressed && styles.pressed]}>
              <Text style={styles.closeText}>닫기</Text>
            </Pressable>
          </View>
          {copy.hint ? <Text style={styles.hint}>{copy.hint}</Text> : null}
          {status === "loading" ? (
            <View style={styles.center} accessibilityLiveRegion="polite">
              <ActivityIndicator color={colors.accent} />
            </View>
          ) : null}
          {status === "error" ? (
            <View style={styles.center} accessibilityLiveRegion="polite">
              <Text style={styles.message}>{error}</Text>
              <Pressable onPress={onRetry} accessibilityRole="button" accessibilityLabel="다시 시도" style={({ pressed }) => [styles.retry, pressed && styles.pressed]}>
                <Text style={styles.retryText}>다시 시도</Text>
              </Pressable>
            </View>
          ) : null}
          {status === "ready" && items.length === 0 ? (
            <View style={styles.center}>
              <Text style={styles.message}>{copy.empty}</Text>
            </View>
          ) : null}
          {status === "ready" && items.length > 0 ? (
            <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
              {items.map((item) => (
                <Pressable
                  key={item.key}
                  onPress={() => onPick(item)}
                  accessibilityRole="button"
                  accessibilityLabel={`${item.badge} ${item.title}${item.line ? `, ${item.line}` : ""}, 누르면 공유 확인`}
                  style={({ pressed }) => [styles.item, pressed && styles.pressed]}
                >
                  <View style={styles.icon}>
                    <Ionicons name={ICON[item.badge] ?? "calendar-outline"} size={20} color={colors.accent} />
                  </View>
                  <View style={styles.texts}>
                    <Text style={styles.itemTitle} numberOfLines={1}>
                      {item.title}
                    </Text>
                    {item.line ? (
                      <Text style={styles.itemLine} numberOfLines={1}>
                        {item.line}
                      </Text>
                    ) : null}
                  </View>
                  <Text style={styles.badge}>{item.badge}</Text>
                </Pressable>
              ))}
            </ScrollView>
          ) : null}
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.dark, opacity: 0.3 },
  sheet: { backgroundColor: colors.card, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, maxHeight: "70%" },
  handle: { alignSelf: "center", width: 36, height: 4, borderRadius: radius.pill, backgroundColor: colors.divider, marginVertical: spacing.sm },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  title: { ...font.section, color: colors.text, flex: 1 },
  close: { minHeight: 44, paddingHorizontal: spacing.sm, alignItems: "center", justifyContent: "center", borderRadius: radius.md },
  closeText: { ...font.bodyStrong, color: colors.textSub },
  hint: { ...font.caption, color: colors.textMuted, marginBottom: spacing.sm },
  center: { minHeight: 96, alignItems: "center", justifyContent: "center", gap: spacing.sm, paddingVertical: spacing.lg },
  message: { ...font.body, color: colors.textSub, textAlign: "center" },
  retry: { minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.button, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  retryText: { ...font.bodyStrong, color: colors.text },
  list: { flexGrow: 0 },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56, paddingHorizontal: spacing.xs, borderRadius: radius.md },
  pressed: { backgroundColor: colors.surface },
  icon: { width: 36, height: 36, borderRadius: radius.md, backgroundColor: colors.honeySoft, alignItems: "center", justifyContent: "center" },
  texts: { flex: 1, minWidth: 0 },
  itemTitle: { ...font.bodyStrong, color: colors.text },
  itemLine: { ...font.caption, color: colors.textSub },
  badge: { ...font.caption, color: colors.textMuted },
});
