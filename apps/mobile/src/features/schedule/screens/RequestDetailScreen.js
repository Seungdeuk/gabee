import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import ConfirmDialog from "../components/ConfirmDialog";
import RecipientsSheet from "../components/RecipientsSheet";
import StatusBadge from "../components/StatusBadge";
import { ME_ID } from "../mock";
import { sentStatus, whoLabels } from "../model";
import { cancelMessage } from "../recipients_edit";
import { cancelRequest, changeRecipients, useRequest } from "../requests";
import { useMembers } from "../store";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";

const TOAST_MS = 2400;

/**
 * 보낸 부탁의 상세(보낸 사람 화면). 상태 배지, 내용, "내가 보냈어요", 정보 카드(받는 분·함께해요)를 보여 준다.
 * 받는 분 줄 옆 [바꾸기]로 받는 사람을 바꾸고(시트), 함께해요에는 수락한 사람만 나온다(기다리는 사람과 어렵다고 한 사람은 표시하지 않는다).
 * 아래 [부탁 취소하기]는 수락한 사람이 있어도 누를 수 있다(수락한 사람의 일정은 서버가 지운다).
 */
export default function RequestDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams();
  const request = useRequest(typeof id === "string" ? id : "");
  const family = useMembers();
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  const toastTimer = useRef(null);
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/schedule/together-status"));
  const nameOf = (memberId) => family.find((m) => m.id === memberId)?.name ?? "";

  if (!request) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.body}>
          <IconButton name="chevron-back" label="뒤로" onPress={leave} />
        </View>
      </SafeAreaView>
    );
  }

  const status = sentStatus(request);
  const cancelled = status === "cancelled";
  const time = formatTimeConfirmed(request);
  const labels = whoLabels(request.whoIds, family);
  const together = request.toIds.filter((toId) => request.replies[toId] === "accepted").map(nameOf);
  const candidates = family.filter((m) => m.id !== ME_ID && m.hasAccount);
  const rows = [
    ["날짜", formatDateWithYear(request.date)],
    time ? ["시간", time] : null,
    request.place ? ["장소", request.place] : null,
    labels.length > 0 ? ["누구", labels.join(", ")] : null,
    request.memo ? ["메모", request.memo] : null,
  ].filter(Boolean);

  const showToast = (text) => {
    setToast(text);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), TOAST_MS);
  };
  const save = async (toIds) => {
    setSaving(true);
    const ok = await changeRecipients(request.id, toIds);
    setSaving(false);
    if (ok) setEditing(false);
    showToast(ok ? "받는 사람을 바꿨어요" : "받는 사람을 바꾸지 못했어요. 잠시 뒤 다시 해 주세요");
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.back}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
            </View>
          </View>

          <View style={styles.head}>
            <StatusBadge status={status} />
            <Text style={styles.title} accessibilityRole="header">
              {request.title}
            </Text>
            <Text style={styles.by}>내가 보냈어요</Text>
          </View>

          <View style={styles.info}>
            {rows.map(([label, value], i) => (
              <View key={label} style={[styles.row, i > 0 && styles.rowBorder]}>
                <Text style={styles.label}>{label}</Text>
                <Text style={styles.value}>{value}</Text>
              </View>
            ))}
            <View style={[styles.row, styles.rowBorder]}>
              <Text style={styles.label}>받는 분</Text>
              <View style={styles.valueRow}>
                <Text style={styles.valueFlex}>{request.toIds.map(nameOf).join(", ")}</Text>
                {cancelled ? null : (
                  <Pressable onPress={() => setEditing(true)} style={styles.change} accessibilityRole="button">
                    <Text style={styles.changeText}>바꾸기</Text>
                  </Pressable>
                )}
              </View>
            </View>
            {together.length > 0 ? (
              <View style={[styles.row, styles.rowBorder]}>
                <Text style={styles.label}>함께해요</Text>
                <View style={styles.together}>
                  {together.map((name) => (
                    <View key={name} style={styles.togetherItem}>
                      <Text style={styles.value}>{name}</Text>
                      <Text style={styles.mini}>수락</Text>
                    </View>
                  ))}
                </View>
              </View>
            ) : null}
          </View>

          {cancelled ? null : (
            <Pressable onPress={() => setConfirming(true)} style={styles.cancelButton} accessibilityRole="button">
              <Text style={styles.cancelText}>부탁 취소하기</Text>
            </Pressable>
          )}
        </View>
      </ScrollView>

      {editing ? (
        <RecipientsSheet
          candidates={candidates}
          current={request.toIds}
          replies={request.replies}
          saving={saving}
          onClose={() => setEditing(false)}
          onSave={save}
        />
      ) : null}
      {toast ? (
        <View style={styles.toast} pointerEvents="none" accessibilityRole="alert">
          <Text style={styles.toastText}>{toast}</Text>
        </View>
      ) : null}

      <ConfirmDialog
        visible={confirming}
        title="부탁을 취소할까요?"
        message={cancelMessage(together.length > 0)}
        cancelLabel="돌아가기"
        confirmLabel="취소하기"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          cancelRequest(request.id);
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 18 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  back: { marginLeft: -spacing.md },
  head: { gap: 3 },
  title: { ...font.page, color: colors.text },
  by: { ...font.bodyStrong, fontWeight: "400", color: colors.textMuted },
  info: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 6,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
  },
  row: { flexDirection: "row", gap: 10, paddingVertical: 8 },
  rowBorder: { borderTopWidth: 1, borderTopColor: colors.border },
  label: { width: 62, fontSize: 14, fontWeight: "500", color: colors.textMuted, paddingTop: 2 },
  value: { flex: 1, fontSize: 16, color: colors.text },
  valueRow: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  valueFlex: { flexShrink: 1, fontSize: 16, color: colors.text },
  change: {
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  changeText: { fontSize: 13, fontWeight: "500", color: "#F08F6C" },
  together: { flex: 1, flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 10 },
  togetherItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  mini: {
    ...font.caption,
    fontWeight: "700",
    paddingHorizontal: 8,
    borderRadius: radius.pill,
    overflow: "hidden",
    color: colors.onDark,
    backgroundColor: colors.success,
  },
  cancelButton: {
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.button,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelText: { fontSize: 15, fontWeight: "500", color: colors.textMuted },
  toast: {
    position: "absolute",
    left: spacing.xxl,
    right: spacing.xxl,
    bottom: spacing.xxl,
    padding: 12,
    borderRadius: radius.button,
    backgroundColor: colors.text,
  },
  toastText: { fontSize: 14, textAlign: "center", color: colors.background },
});
