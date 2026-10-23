import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import ConfirmDialog from "../components/ConfirmDialog";
import StatusBadge from "../components/StatusBadge";
import { members } from "../mock";
import { sentStatus, whoLabels } from "../model";
import { cancelRequest, useRequest } from "../requests";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";

const nameOf = (id) => members.find((m) => m.id === id)?.name ?? "";

/**
 * 보낸 같이의 상세(보낸 사람 화면). 상태 배지, 내용, "내가 보냈어요", 정보 카드, 함께하는 사람을 보여 준다.
 * 함께해요에는 수락한 사람만 나오고(기다리는 사람과 어렵다고 한 사람은 표시하지 않는다), 보내기 취소는 답을 기다리는 동안에만 보인다.
 */
export default function RequestDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams();
  const request = useRequest(typeof id === "string" ? id : "");
  const [confirming, setConfirming] = useState(false);

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/schedule/together-status"));

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
  const time = formatTimeConfirmed(request);
  const labels = whoLabels(request.whoIds, members);
  const together = request.toIds.filter((toId) => request.replies[toId] === "accepted").map(nameOf);
  const rows = [
    ["날짜", formatDateWithYear(request.date)],
    time ? ["시간", time] : null,
    request.place ? ["장소", request.place] : null,
    labels.length > 0 ? ["누구", labels.join(", ")] : null,
    request.memo ? ["메모", request.memo] : null,
  ].filter(Boolean);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.back}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
            </View>
            {status === "pending" ? (
              <Pressable onPress={() => setConfirming(true)} style={styles.pill} accessibilityRole="button">
                <Text style={styles.pillText}>보내기 취소</Text>
              </Pressable>
            ) : null}
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
          </View>

          {together.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.heading}>함께해요</Text>
              <View style={styles.info}>
                <View style={styles.together}>
                  {together.map((name) => (
                    <Text key={name} style={styles.who}>
                      {name}
                    </Text>
                  ))}
                </View>
              </View>
            </View>
          ) : null}
        </View>
      </ScrollView>

      <ConfirmDialog
        visible={confirming}
        title="보낸 걸 취소할까요?"
        message={`${request.toIds.map(nameOf).join(", ")} 화면에서도 사라져요.`}
        cancelLabel="아니요"
        confirmLabel="취소할게요"
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
  pill: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  pillText: { fontSize: 14, fontWeight: "500", color: colors.text },
  head: { gap: 6 },
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
  row: { flexDirection: "row", gap: 10, paddingVertical: 11 },
  rowBorder: { borderTopWidth: 1, borderTopColor: colors.border },
  label: { width: 62, fontSize: 14, fontWeight: "500", color: colors.textMuted, paddingTop: 2 },
  value: { flex: 1, fontSize: 16, color: colors.text },
  section: { gap: spacing.md },
  heading: { ...font.title, color: colors.text },
  together: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 12 },
  who: {
    fontSize: 14,
    fontWeight: "500",
    color: colors.text,
    backgroundColor: colors.surfaceStrong,
    paddingHorizontal: 12,
    paddingVertical: 2,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
});
