import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import SegmentedControl from "../components/SegmentedControl";
import StatusBadge from "../components/StatusBadge";
import { ME_ID, members } from "../mock";
import { sentStatus } from "../model";
import { useRequests } from "../requests";
import { formatDateLong, todayKey } from "../utils/date";

const TAB_OPTIONS = [
  { key: "received", label: "받은" },
  { key: "sent", label: "보낸" },
];

/** 지난 구역에서 먼저 보이는 개수. 나머지는 "이전 기록 더 보기". */
const PAST_PREVIEW = 3;

const nameOf = (id) => members.find((m) => m.id === id)?.name ?? "";

/**
 * 주고 받은(전 현황): 같이의 메인 화면. [받은 | 보낸] 두 탭, 구역은 "답을 기다려요" / "함께해요"(수락됐고 아직 날짜가 안 지난 것) / "지난"(숫자 없이 최근 몇 개 + 이전 기록 더 보기).
 * 오른쪽 위 "같이하기"로 새로 보내고, ‹는 일정 메인으로 돌아간다. 지금은 보낸 쪽만 있고 받은 쪽(받기)은 다음 PR에서 붙인다.
 */
export default function TogetherStatusScreen() {
  const router = useRouter();
  const requests = useRequests();
  const [tab, setTab] = useState("sent");
  const [morePast, setMorePast] = useState(false);

  const sent = requests.filter((r) => r.fromId === ME_ID);
  const today = todayKey();
  const waiting = sent.filter((r) => sentStatus(r) === "pending");
  // 수락됐고 아직 날짜가 지나지 않은 것은 함께해요, 날짜가 지났거나 취소된 것은 지난에 둔다.
  const together = sent
    .filter((r) => sentStatus(r) === "accepted" && r.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date));
  const past = sent
    .filter((r) => sentStatus(r) === "cancelled" || (sentStatus(r) === "accepted" && r.date < today))
    .sort((a, b) => b.date.localeCompare(a.date));
  const pastShown = morePast ? past : past.slice(0, PAST_PREVIEW);

  // 일정 메인에서 들어왔으므로 ‹는 일정 메인으로 간다.
  const leave = () => router.dismissTo("/(tabs)/schedule");
  const open = (id) => router.push({ pathname: "/schedule/together-detail", params: { id } });

  const card = (r) => (
    <Pressable key={r.id} onPress={() => open(r.id)} style={styles.card} accessibilityRole="button">
      <View style={styles.cardMain}>
        <Text style={styles.cardTitle}>{r.title}</Text>
        <Text style={styles.cardSub}>
          {`${r.toIds.map(nameOf).join(", ")} · ${formatDateLong(r.date)}${r.startTime ? ` ${r.startTime}` : ""}`}
        </Text>
      </View>
      <StatusBadge status={sentStatus(r)} />
    </Pressable>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.titleBox}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
              <Text style={styles.title} accessibilityRole="header">
                주고 받은
              </Text>
            </View>
            <Pressable
              onPress={() => router.push({ pathname: "/schedule/together", params: { from: "status" } })}
              style={styles.send}
              accessibilityRole="button"
            >
              <Text style={styles.sendText}>같이하기</Text>
            </Pressable>
          </View>

          <SegmentedControl options={TAB_OPTIONS} value={tab} onChange={setTab} full dark />

          {tab === "received" ? (
            <Text style={styles.empty}>받은 게 아직 없어요</Text>
          ) : (
            <>
              <View style={styles.section}>
                <View style={styles.head}>
                  <Text style={styles.heading}>답을 기다려요</Text>
                  {waiting.length > 0 ? <Text style={styles.count}>{`${waiting.length}개`}</Text> : null}
                </View>
                {waiting.length === 0 ? <Text style={styles.empty}>기다리는 게 없어요</Text> : waiting.map(card)}
              </View>

              {together.length > 0 ? (
                <View style={styles.section}>
                  <View style={styles.head}>
                    <Text style={styles.heading}>함께해요</Text>
                    <Text style={styles.count}>{`${together.length}개`}</Text>
                  </View>
                  {together.map(card)}
                </View>
              ) : null}

              {past.length > 0 ? (
                <View style={styles.section}>
                  <Text style={styles.heading}>지난</Text>
                  {pastShown.map(card)}
                  {!morePast && past.length > PAST_PREVIEW ? (
                    <Pressable onPress={() => setMorePast(true)} style={styles.more} accessibilityRole="button">
                      <Text style={styles.moreText}>이전 기록 더 보기</Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}
            </>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 18 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  titleBox: { flexDirection: "row", alignItems: "center", flexShrink: 1, marginLeft: -spacing.sm },
  send: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: colors.peach },
  sendText: { fontSize: 14, fontWeight: "700", color: colors.text },
  title: { ...font.page, color: colors.text },
  section: { gap: spacing.md },
  head: { flexDirection: "row", alignItems: "baseline", gap: spacing.sm },
  heading: { ...font.title, color: colors.text },
  count: { ...font.bodyStrong, fontWeight: "500", color: colors.textMuted },
  empty: { ...font.body, color: colors.textMuted },
  card: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
  },
  cardMain: { flex: 1, gap: 2 },
  cardTitle: { fontSize: 16, color: colors.text },
  cardSub: { ...font.caption, color: colors.textMuted },
  more: {
    alignItems: "center",
    paddingVertical: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.button,
  },
  moreText: { fontSize: 14, fontWeight: "500", color: colors.textMuted },
});
